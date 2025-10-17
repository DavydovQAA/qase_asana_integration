# QASE → Asana

Создает задачи в Asana из JSON экспорта QASE.

## Установка

```bash
pip3 install requests python-dotenv
```

## Настройка

Создать `.env`:
```
ASANA_TOKEN=ваш_токен
```

Токен: https://app.asana.com/ → Settings → Apps → Personal Access Token

## Запуск

```bash
python3 main.py
```

Ввести путь к JSON файлу (или Enter для `qase_export.json`).

## Что делает

Создает **иерархию задач** из QASE в Asana:
- Суиты → задачи/subtasks
- Кейсы → subtasks с названием `[TMM-123] Название`
- Описание кейса: `https://app.qase.io/case/TMM-123`
- Добавляет в оба проекта: TS QAA Main и Shelf

Пример структуры:
```
📁 Offline (задача)
   └─ Первый запуск (subtask)
       └─ [TMM-123] Кейс (subtask)
```

## Настройки

В `config.py`:

```python
QASE_PROJECT_CODE = "TMM"
ASANA_PROJECT_MAIN_GID = "1200923340924452"
ASANA_PROJECT_SHELF_GID = "1211301691736509"
```

## Структура

```
├── config.py    # настройки
└── main.py      # скрипт (~260 строк)
```

## TeamCity

Скрипт работает **и локально, и в TeamCity**:

**Build Step:**
```bash
export JSON_FILE_PATH="%json_file_path%"
pip3 install requests python-dotenv
python3 main.py
```

**Parameters:**
- `json_file_path` - Configuration Parameter (text, prompt)
- `ASANA_TOKEN` - Environment Variable (password)

**Exit codes:** `0` = success, `1` = failed

# qase_asana_integration
