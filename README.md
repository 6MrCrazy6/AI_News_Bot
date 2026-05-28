# AI News Bot

A Telegram bot for automatic tracking, ranking, and publishing of AI-related news from various sources.

## Table of Contents

- [Features](#features)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Installation and Setup](#installation-and-setup)
- [Running](#running)
- [Testing](#testing)
- [Administration](#administration)
- [Source Configuration](#source-configuration)
- [Monitoring and Logging](#monitoring-and-logging)
- [Extending Functionality](#extending-functionality)
- [Notes](#notes)
- [Troubleshooting](#troubleshooting)
- [License](#license)

## Features

- 🤖 Automatic news aggregation from RSS feeds, GitHub Trending, JSON Feeds, and APIs  
- 🔍 Deduplication and removal of duplicate news  
- ⭐ News ranking based on impact and freshness  
- 📝 **AI-powered Summarization & Translation** using OpenRouter (Nemotron-3-Nano)
- ⚡ **High-Performance Parallel Processing**: Concurrent LLM calls for 10x faster processing
- 🗄️ **Optimized SQLite Database**: WAL mode, connection pooling, and indexing for reliability
- 🔄 **Smart Retries**: Exponential backoff for OpenRouter API calls
- 📢 Instant publishing of breaking news and robust daily digests with automatic message splitting
- 🌍 Support for both Russian and English languages  
- 👍 Popularity tracking via user likes on news posts  

## Project Structure

```
ai-news-bot/
├── app/
│   ├── database/         # Database directory (auto-created)
│   ├── fetchers/         # Modules for fetching news
│   │   ├── Config/
│   │   │   └── config.json  # Source configuration
│   │   ├── base.py       # Base fetcher class
│   │   ├── github.py     # GitHub trending fetcher
│   │   ├── rss.py        # RSS feed fetcher
│   │   ├── taaft.py      # TheresAnAIForThat API fetcher
│   │   └── json_feed.py  # JSON Feed universal fetcher
│   ├── bot.py            # Telegram bot handlers
│   ├── common.py         # Shared utilities and logger
│   ├── db.py             # SQLite database handling (Optimized)
│   ├── llm_processor.py  # Integration with OpenRouter (Parallel)
│   ├── ranker.py         # News ranking logic
│   ├── scheduler.py      # Task scheduler and main entry point
│   └── summarizer.py     # News processing pipeline
├── keys/                 # API keys and environment variables
│   └── keys.env          # Keys file (gitignore recommended)
├── tests/                # Tests and wrappers
│   └── bot_wrapper.py
├── requirements.txt      # Project dependencies
├── LICENSE               # CC BY-NC 4.0 License
└── README.md             # Project documentation
```

## Requirements

- Python 3.11  
- Telegram Bot API Token  
- **OpenRouter API Key** (for high-quality translation and summarization)
- Internet access to work with news sources  

## Installation and Setup

### 1. Clone the repository

```bash
git clone https://github.com/6MrCrazy6/AI_News_Bot.git
cd AI_News_Bot
```

### 2. Set environment variables

Create the file `keys/keys.env` with the following content:

```
TELEGRAM_TOKEN=your_telegram_bot_token
TG_CHANNEL_ID=your_channel_id
OPENROUTER_API_KEY=your_openrouter_api_key
OPENROUTER_MODEL=nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free
DB_URL=app/database/news.db
```

Where:
- `your_telegram_bot_token` - Token from @BotFather  
- `your_channel_id` - Telegram channel ID (format: -100xxxxxxxxxx)  
- `your_openrouter_api_key` - Key from OpenRouter.ai

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

## Running

### Start the bot (for testing)

```bash
# Run the bot handlers only
python -m app.bot
```

### Start full service (Recommended)

```bash
# Run the scheduler with the bot (Full automation)
python -m app.scheduler
```

## Administration

### Telegram Bot Commands

**General Commands:**
- `/help` – Explains how to use the bot and its features  
- `/stats` – News statistics for the past week  
- `/top_news [days] [count]` – Shows the top-N most liked news items  
- `/source_stats [days]` – Shows performance rating of news sources  
- `/healthz` – Bot health check  
- `/list_sources` – Lists all configured news sources  

**Admin Commands:**
- `/toggle [source_id]` – Enable/disable a specific news source  
- `/process_source [source_id]` – Manually process a specific source  
- `/digest now` – Send the digest immediately  
- `/breaking` – Publish urgent breaking news immediately  
- `/db_status` – Show database status

## Source Configuration

News sources are configured in `app/fetchers/Config/config.json`. Format:

```json
{
  "source_id": {
    "type": "source_type",
    "url": "source_url",
    "interval": 60,
    "lang": "en"
  }
}
```

Source types:
- `rss` – RSS feeds  
- `scrap` – Web scraping (GitHub)  
- `api` – API integrations (TAAFT)
- `json_feed` – JSON Feed standard

## Extending Functionality

### Adding a new source

1. Add configuration in `app/fetchers/Config/config.json`  
2. If a new source type is needed, create a fetcher class in `app/fetchers` inheriting from `BaseFetcher`
3. Register the class in `FETCHER_CLASSES` in `app/scheduler.py`  

## Notes

- **OpenRouter** is used for high-quality translation and summarization.
- Breaking news (impact ≥ 4) is published immediately, others are compiled into a digest.
- The digest is sent at 08:00 Kyiv time by default.

## Troubleshooting

### Common issues:

1. **ModuleNotFoundError**
   - Ensure you are running the bot from the project root using `python -m app.scheduler`.

2. **Bot not sending messages to channel**  
   - Make sure the bot is added as an admin in the channel.
   - Ensure the channel ID is correct (including `-100` prefix).

3. **OpenRouter API errors**  
   - Check that your API key is valid. The bot now includes **exponential backoff retries** for better stability.

## License

This project is licensed under the **Creative Commons Attribution-NonCommercial 4.0 International (CC BY-NC 4.0)** License.

- **NonCommercial** — You may not use the material for commercial purposes.
- **Attribution** — You must give appropriate credit, provide a link to the license, and indicate if changes were made.

For more details, see the [LICENSE](LICENSE) file.
