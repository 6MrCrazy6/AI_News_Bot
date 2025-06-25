# AI News Bot

A Telegram bot for automatic tracking, ranking, and publishing of AI-related news from various sources.

## Features

- 🤖 Automatic news aggregation from RSS feeds, GitHub Trending, and APIs  
- 🔍 Deduplication and removal of duplicate news  
- ⭐ News ranking based on impact and freshness  
- 📝 Automatic summarization using Gemini Flash and GPT-4o  
- 📢 Instant publishing of breaking news and daily digests  
- 🌍 Support for both Russian and English languages  
- 👍 Popularity tracking via user likes on news posts  

## Project Structure

```
ai-news-bot/
├── app/
│   ├── database/         # Database directory
│   ├── fetchers/         # Modules for fetching news
│   │   ├── Config/
│   │   │   └── config.json  # Source configuration
│   │   ├── base.py       # Base fetcher class
│   │   ├── github.py     # GitHub trending fetcher
│   │   ├── rss.py        # RSS feed fetcher
│   │   └── taaft.py      # TheresAnAIForThat API fetcher
│   ├── bot.py            # Telegram bot
│   ├── db.py             # SQLite database handling
│   ├── llm_processor.py  # Integration with LLMs (Gemini, GPT-4o)
│   ├── ranker.py         # News ranking
│   ├── scheduler.py      # Task scheduler
│   └── summarizer.py     # News summarization and processing
├── keys/                 # API keys and environment variables
│   └── keys.env          # Keys file
├── tests/                # Tests
│   ├── test_ranker.py
│   └── test_summarizer.py
├── Pipfile               # Pipenv dependencies
└── README.md             # Project documentation
```

## Requirements

- Python 3.11  
- Telegram Bot API Token  
- API Keys: OpenAI API (for GPT-4o) and Google AI API (for Gemini)  
- Internet access to work with news sources  

## Installation and Setup

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/ai-news-bot.git
cd ai-news-bot
```

### 2. Set environment variables

Create the file `keys/keys.env` with the following content:

```
TELEGRAM_TOKEN=your_telegram_bot_token
TG_CHANNEL_ID=your_channel_id
OPENAI_API_KEY=your_openai_api_key
GOOGLE_API_KEY=your_google_api_key
DB_URL=app/database/news.db
```

Where:
- `your_telegram_bot_token` - Token from @BotFather  
- `your_channel_id` - Telegram channel ID (format: -100xxxxxxxxxx)  
- `your_openai_api_key` - OpenAI key for GPT-4o  
- `your_google_api_key` - Google AI key for Gemini  

### 3. Install dependencies

Using Pipenv:

```bash
# Install Pipenv (if not installed)
pip install pipenv

# Install dependencies
pipenv install
```

## Running

### Start the bot (for testing)

```bash
# Activate virtual environment
pipenv shell

# Run the bot
python -m app.bot
```

### Start full service

```bash
# Activate virtual environment
pipenv shell

# Run the scheduler with the bot
python -m app.scheduler
```

## Testing

### Run all tests

```bash
pipenv run pytest tests/
```

### Run a specific test

```bash
pipenv run pytest tests/test_ranker.py
```

## Administration

### Telegram Bot Commands

**General Commands:**
- `/help` – Explains how to use the bot and its features  
- `/stats` – News statistics for the past week  
- `/top_news [days] [count]` – Shows the top-N most liked news items  
- `/source_stats [days]` – Shows performance rating of news sources  
- `/language_stats [days]` – Statistics on news language usage  
- `/healthz` – Bot health check  
- `/list_sources` – Lists all configured news sources  

**Admin Commands:**
- `/toggle [source_id]` – Enable/disable a specific news source  
- `/process_source [source_id]` – Manually process a specific source  
- `/digest now` – Send the digest immediately  
- `/breaking` – Publish urgent breaking news immediately  
- `/reactions [days]` – Reaction statistics for the last N days  
- `/source_info [source_id]` – Detailed information about a source  
- `/db_status` – Show database status

## Source Configuration

News sources are configured in `app/fetchers/Config/config.json`. Format:

```json
{
  "source_id": {
    "type": "source_type",
    "url": "source_url",
    "interval": "check_interval_minutes",
    "lang": "source_language"
  }
}
```

Source types:
- `rss` – RSS feeds  
- `scrap` – Web scraping (GitHub)  
- `api` – API integrations  

## Monitoring and Logging

Logs are saved in JSON format using `structlog`. Use appropriate tools or `tail -f` to monitor logs during execution.

## Extending Functionality

### Adding a new source

1. Add configuration in `app/fetchers/Config/config.json`  
2. If a new source type is needed, create a fetcher class in `app/fetchers`  
3. Register the class in `FETCHER_CLASSES` in `app/scheduler.py`  

## Notes

- Gemini and GPT-4o API keys are required for full functionality  
- Breaking news (impact ≥ 4) is published immediately, others are compiled into a digest  
- The digest is sent at 07:30 Kyiv time by default  

## Troubleshooting

### Common issues:

1. **Bot not sending messages to channel**  
   - Make sure the bot is added as an admin in the channel  
   - Ensure the channel ID is correct (including `-100` prefix)  

2. **LLM API errors**  
   - Check that API keys are valid  
   - Ensure the account still has available credits