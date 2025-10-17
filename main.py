#!/usr/bin/env python3
import json
import os
import sys
import time
import requests
from dotenv import load_dotenv
from config import *


# === JSON Parser ===

def parse_qase_json(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    if not isinstance(data, dict) or "suites" not in data:
        raise ValueError("Expected JSON format: {\"suites\": [...]}")
    
    def build_tree(suite):
        return {
            "id": suite.get("id"),
            "title": suite.get("title", "Untitled"),
            "cases": suite.get("cases", []),
            "suites": [build_tree(s) for s in suite.get("suites", [])] if isinstance(suite.get("suites"), list) else []
        }
    
    suites_data = data["suites"]
    if isinstance(suites_data, dict):
        suites_data = list(suites_data.values())
    
    root_suites = [build_tree(s) for s in suites_data]
    
    # Убираем пустые wrapper'ы первого уровня
    filtered = []
    for suite in root_suites:
        if not suite["cases"] and suite["suites"]:
            # Пустой wrapper - берем его детей
            filtered.extend(suite["suites"])
        else:
            filtered.append(suite)
    
    return filtered


def count_all(suites):
    total_suites = 0
    total_cases = 0
    for suite in suites:
        s, c = _count_suite(suite)
        total_suites += s
        total_cases += c
    return total_suites, total_cases

def _count_suite(suite):
    suites_count = 1
    cases_count = len(suite.get("cases", []))
    for nested in suite.get("suites", []):
        s, c = _count_suite(nested)
        suites_count += s
        cases_count += c
    return suites_count, cases_count


# === Asana API ===

session = None
last_request_time = None

def _rate_limit():
    global last_request_time
    if last_request_time:
        interval = 1.0 / ASANA_RATE_LIMIT
        elapsed = time.time() - last_request_time
        if elapsed < interval:
            time.sleep(interval - elapsed)
    last_request_time = time.time()

def _asana_request(method, endpoint, token, **kwargs):
    global session
    if not session:
        session = requests.Session()
    
    url = f"{ASANA_API_BASE.rstrip('/')}/{endpoint.lstrip('/')}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    
    for attempt in range(RETRY_ATTEMPTS):
        try:
            _rate_limit()
            resp = session.request(method, url, headers=headers, timeout=REQUEST_TIMEOUT, **kwargs)
            resp.raise_for_status()
            return resp
        except requests.exceptions.RequestException as e:
            if attempt == RETRY_ATTEMPTS - 1:
                raise
            time.sleep(RETRY_DELAY)

def verify_project(token, project_gid):
    try:
        resp = _asana_request("GET", f"/projects/{project_gid}", token)
        name = resp.json().get("data", {}).get("name", "Unknown")
        print(f"✓ Project: {name}")
        return True
    except Exception as e:
        print(f"✗ Failed: {e}")
        return False

def create_task(token, name, notes, projects):
    """Создает задачу. Returns: (success, gid, url)"""
    try:
        resp = _asana_request("POST", "/tasks", token, 
                              json={"data": {"name": name, "notes": notes, "projects": projects}})
        gid = resp.json().get("data", {}).get("gid")
        if gid:
            url = ASANA_TASK_URL_TEMPLATE.format(project=projects[0], task=gid)
            return True, gid, url
        return False, None, None
    except Exception:
        return False, None, None

def create_subtask(token, parent_gid, name, notes):
    """Создает subtask. Returns: (success, gid, url)"""
    try:
        resp = _asana_request("POST", f"/tasks/{parent_gid}/subtasks", token,
                              json={"data": {"name": name, "notes": notes}})
        gid = resp.json().get("data", {}).get("gid")
        if gid:
            url = ASANA_TASK_URL_TEMPLATE.format(project="0", task=gid)
            return True, gid, url
        return False, None, None
    except Exception:
        return False, None, None


# === Processing ===

def process_suite(suite, token, parent_gid=None, indent=0):
    title = suite["title"]
    prefix = "  " * indent
    
    # Создаем задачу для suite
    if parent_gid is None:
        projects = [ASANA_PROJECT_MAIN_GID, ASANA_PROJECT_SHELF_GID]
        ok, gid, url = create_task(token, title, "", projects)
    else:
        ok, gid, url = create_subtask(token, parent_gid, title, "")
    
    if not ok or not gid:
        print(f"{prefix}✗ Suite '{title}' failed")
        return {"suites": 0, "cases": 0, "failed": len(suite.get("cases", []))}
    
    print(f"{prefix}📁 {title}")
    if url:
        print(f"{prefix}   {url}")
    
    stats = {"suites": 1, "cases": 0, "failed": 0}
    
    # Создаем subtasks для кейсов
    for case in suite.get("cases", []):
        if not case.get("id") or not case.get("title"):
            continue
        
        case_id = case["id"]
        case_title = case["title"]
        task_name = f"[{QASE_PROJECT_CODE}-{case_id}] {case_title}"
        task_notes = QASE_CASE_URL_TEMPLATE.format(project=QASE_PROJECT_CODE, id=case_id)
        
        ok, _, url = create_subtask(token, gid, task_name, task_notes)
        if ok:
            stats["cases"] += 1
            if url:
                print(f"{prefix}   ✓ {url}")
        else:
            stats["failed"] += 1
            print(f"{prefix}   ✗ [{QASE_PROJECT_CODE}-{case_id}] Failed")
    
    # Рекурсия для вложенных suites
    for nested in suite.get("suites", []):
        nested_stats = process_suite(nested, token, gid, indent + 1)
        stats["suites"] += nested_stats["suites"]
        stats["cases"] += nested_stats["cases"]
        stats["failed"] += nested_stats["failed"]
    
    return stats


# === Main ===

def main():
    load_dotenv()
    
    print("=" * 70)
    print("QASE → ASANA")
    print("=" * 70)
    
    token = os.getenv("ASANA_TOKEN")
    if not token:
        print("✗ ASANA_TOKEN not found in .env")
        sys.exit(1)
    print("✓ Token loaded")
    
    print("\nVerifying projects...")
    if not verify_project(token, ASANA_PROJECT_MAIN_GID):
        sys.exit(1)
    if not verify_project(token, ASANA_PROJECT_SHELF_GID):
        sys.exit(1)
    
    print()
    # TeamCity: читаем из env, fallback на input
    json_file = os.getenv("JSON_FILE_PATH")
    if json_file:
        print(f"Using JSON from env: {json_file}")
    else:
        json_file = input("JSON file (Enter = qase_export.json): ").strip() or "qase_export.json"
    
    if not os.path.exists(json_file):
        print(f"✗ Not found: {json_file}")
        sys.exit(1)
    
    print(f"\nParsing: {json_file}")
    try:
        suites = parse_qase_json(json_file)
    except Exception as e:
        print(f"✗ Parse error: {e}")
        sys.exit(1)
    
    total_suites, total_cases = count_all(suites)
    print(f"✓ Found {total_suites} suites, {total_cases} cases")
    
    if total_suites == 0:
        print("Nothing to do")
        return
    
    print(f"\nCreating tasks...")
    print("-" * 70)
    
    all_stats = {"suites": 0, "cases": 0, "failed": 0}
    
    for suite in suites:
        stats = process_suite(suite, token)
        all_stats["suites"] += stats["suites"]
        all_stats["cases"] += stats["cases"]
        all_stats["failed"] += stats["failed"]
        print()
    
    print("-" * 70)
    print("\nCOMPLETED")
    print(f"Suites:  {all_stats['suites']}/{total_suites}")
    print(f"Cases:   {all_stats['cases']}/{total_cases}")
    print(f"Failed:  {all_stats['failed']}")
    if total_cases > 0:
        rate = (all_stats['cases'] / total_cases) * 100
        print(f"Success: {rate:.1f}%")
    print("=" * 70)
    
    # Exit code для TeamCity
    if all_stats['failed'] > 0:
        sys.exit(1)  # Build failed если есть ошибки
    sys.exit(0)  # Success


if __name__ == "__main__":
    main()
