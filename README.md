# Bot Manager (Flask)

## Возможности
- Авторизация (root/root по умолчанию)
- Создание, редактирование, старт/стоп/перезапуск ботов
- Просмотр логов
- Ежедневное авто-обновление репозитория и перезапуск ботов (00:00 по времени сервера)
- Мониторинг логов и уведомления об ошибках в Telegram

## Установка

### 1) Подготовка окружения
```
python -m venv .venv
# Windows
.\.venv\Scripts\activate
# Linux/macOS
source .venv/bin/activate
pip install -r manager/requirements.txt
```

### 2) Переменные окружения (опционально)
- `MANAGER_DATABASE_URL` — строка подключения к БД (по умолчанию sqlite `manager.db`)
- `SECRET_KEY` — секрет для Flask
- `ALERT_BOT_TOKEN` и `ALERT_CHAT_ID` — токен и чат для алертов об ошибках

### 3) Запуск
```
# Dev
python manager/app.py

# Prod (Waitress)
python -m waitress --listen=0.0.0.0:8000 manager.wsgi:app
```

Откройте http://127.0.0.1:5000/ (или порт из запуска). Логин/пароль: `root`/`root`.

## Добавление бота
- Нажмите "Добавить бота"
- Укажите `Repo URL`, например: `https://github.com/MrGAN12009/py_test_tg_bot` ([источник](https://github.com/MrGAN12009/py_test_tg_bot))
- Вставьте токен бота и (опционально) `.env` переменные и `DB URL`
- После создания откройте страницу бота и нажмите "Старт"

## Структура
- `bots/<ИмяБота>/` — рабочая папка каждого бота с `.env`, логами и кодом
- Логи: `bots/<ИмяБота>/logs/bot.out.log` и `bot.err.log`

## Замечания
- По умолчанию ищется входная точка `main.py`, если нет — `k.py`
- Если проектам требуется отдельное виртуальное окружение — можно расширить `start_bot_process` с `venv_path`
- Для PostgreSQL указывайте разные базы в `DB URL` каждого бота
