# AI News Bot

Telegram-бот для автоматического отслеживания, ранжирования и публикации новостей об искусственном интеллекте из различных источников.

## Возможности

- 🤖 Автоматический сбор новостей из RSS-лент, GitHub Trending и API
- 🔍 Дедупликация и исключение повторяющихся новостей
- ⭐ Ранжирование новостей по значимости (Impact) и свежести
- 📝 Автоматическая суммаризация с использованием Gemini Flash и GPT-4o
- 📢 Мгновенная публикация важных новостей (Breaking) и ежедневный дайджест
- 🌍 Поддержка русского и английского языков

## Структура проекта

```
ai-news-bot/
├── app/
│   ├── database/         # Директория с базой данных
│   ├── fetchers/         # Модули для получения новостей
│   │   ├── Config/
│   │   │   └── config.json  # Конфигурация источников
│   │   ├── base.py      # Базовый класс фетчера
│   │   ├── github.py    # Получение трендов с GitHub
│   │   ├── rss.py       # Получение данных из RSS
│   │   └── taaft.py     # API TheresAnAIForThat
│   ├── bot.py           # Telegram-бот
│   ├── db.py            # Работа с базой данных SQLite
│   ├── llm_processor.py # Интеграция с LLM (Gemini, GPT-4o)
│   ├── ranker.py        # Ранжирование новостей
│   ├── scheduler.py     # Планировщик задач
│   └── summarizer.py    # Суммаризация и обработка новостей
├── keys/                # Ключи API и переменные окружения
│   └── keys.env         # Файл с ключами
├── tests/               # Тесты
│   ├── test_ranker.py
│   └── test_summarizer.py
├── Dockerfile           # Конфигурация Docker
├── docker-compose.yml   # Конфигурация Docker Compose
├── Pipfile              # Зависимости для Pipenv
└── README.md            # Документация проекта
```

## Требования

- Python 3.11
- Telegram Bot API Token
- API ключи: OpenAI API (для GPT-4o) и Google AI API (для Gemini)
- Доступ к интернету для работы с источниками

## Установка и настройка

### 1. Клонирование репозитория

```bash
git clone https://github.com/yourusername/ai-news-bot.git
cd ai-news-bot
```

### 2. Настройка переменных окружения

Создайте файл `keys/keys.env` со следующим содержимым:

```
TELEGRAM_TOKEN=your_telegram_bot_token
TG_CHANNEL_ID=your_channel_id
OPENAI_API_KEY=your_openai_api_key
GOOGLE_API_KEY=your_google_api_key
DB_URL=app/database/news.db
```

Где:
- `your_telegram_bot_token` - токен от @BotFather
- `your_channel_id` - ID Telegram-канала (формат: -100xxxxxxxxxx)
- `your_openai_api_key` - ключ OpenAI для GPT-4o
- `your_google_api_key` - ключ Google AI для Gemini

### 3. Установка зависимостей

С использованием Pipenv:

```bash
# Установка Pipenv (если отсутствует)
pip install pipenv

# Установка зависимостей
pipenv install
```

## Запуск

### Запуск бота (для тестирования)

```bash
# Активация виртуального окружения
pipenv shell

# Запуск бота
python -m app.bot
```

### Запуск полного сервиса

```bash
# Активация виртуального окружения
pipenv shell

# Запуск планировщика с ботом
python -m app.scheduler
```

## Тестирование

### Запуск всех тестов

```bash
pipenv run pytest tests/
```

### Запуск конкретного теста

```bash
pipenv run pytest tests/test_ranker.py
```

## Docker

### Сборка и запуск

```bash
# Сборка и запуск
docker-compose up --build

# Запуск в фоновом режиме
docker-compose up -d

# Просмотр логов
docker-compose logs -f

# Остановка
docker-compose down
```

## Администрирование

### Команды бота Telegram

- `/stats` - Статистика новостей за 24 часа и неделю
- `/toggle source_id` - Включить/отключить источник (например, `/toggle bens`)
- `/digest now` - Отправить дайджест вне расписания
- `/healthz` - Проверка работоспособности и количества новостей в очереди

## Конфигурация источников

Источники новостей настраиваются в файле `app/fetchers/Config/config.json`. Формат:

```json
{
  "source_id": {
    "type": "тип_источника",
    "url": "url_источника",
    "interval": "минуты_между_проверками",
    "lang": "язык_источника"
  }
}
```

Типы источников:
- `rss` - RSS-ленты
- `scrap` - Веб-скрапинг (GitHub)
- `api` - API-интеграции

## Мониторинг и логирование

Логи сохраняются в формате JSON с использованием structlog. При запуске в Docker используйте команду `docker-compose logs -f` для отслеживания логов.

## Расширение функциональности

### Добавление нового источника

1. Добавьте настройки в `app/fetchers/Config/config.json`
2. Если нужен новый тип источника, создайте класс-фетчер в директории `app/fetchers`
3. Зарегистрируйте класс в `FETCHER_CLASSES` в файле `app/scheduler.py`

## Примечания

- Для полнофункциональной работы необходимы API-ключи для Gemini и GPT-4o
- Breaking-новости (с impact ≥ 4) отправляются сразу, остальные собираются в дайджест
- Дайджест по умолчанию отправляется в 07:30 по Киеву

## Troubleshooting

### Распространенные проблемы:

1. **Не работает отправка в канал**
   - Проверьте, что бот добавлен в канал как администратор
   - Убедитесь, что ID канала указан правильно (включая `-100` в начале)

2. **Ошибки API LLM**
   - Проверьте действительность ключей API
   - Убедитесь, что у аккаунтов не закончился кредит
