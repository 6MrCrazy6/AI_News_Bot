import asyncio
import os
import sys
import logging

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add parent directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.insert(0, parent_dir)

# Import scheduler functions directly with fixed imports
from tests.bot_wrapper import send_breaking_news, send_digest
from app.db import init_db, add_source
from app.fetchers.rss import RSSFetcher
from app.fetchers.github import GitHubTrendingFetcher
from app.fetchers.taaft import TAAFTFetcher
from app.summarizer import process_news
from app.ranker import compute_score

# Import required libraries
import json
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone

# Initialize scheduler
scheduler = AsyncIOScheduler(timezone=timezone('Europe/Kiev'))

# Define config path
CONFIG_PATH = os.path.join(parent_dir, 'app', 'fetchers', 'Config', 'config.json')

# Map of fetcher types to their classes
FETCHER_CLASSES = {
    'rss': RSSFetcher,
    'scrap': GitHubTrendingFetcher,
    'api': TAAFTFetcher
}


def load_config():
    try:
        logger.info(f"Loading config from: {CONFIG_PATH}")
        with open(CONFIG_PATH, 'r') as f:
            config = json.load(f)
            logger.info(f"Successfully loaded {len(config)} sources from config")
            return config
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return {}


# Process news items from a fetcher
async def process_fetcher_results(source_id, fetcher):
    logger.info(f"Processing results from {source_id}")
    try:
        news_items = await fetcher.fetch()
        logger.info(f"Fetched {len(news_items)} items from {source_id}")

        if not news_items:
            logger.info(f"No news items fetched from {source_id}")
            return 0

        for item in news_items:
            item['source_id'] = source_id

            if 'published' in item and isinstance(item['published'], str):
                try:
                    for fmt in ('%a, %d %b %Y %H:%M:%S %z', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%d %H:%M:%S'):
                        try:
                            item['published'] = datetime.strptime(item['published'], fmt)
                            break
                        except ValueError:
                            continue

                    if isinstance(item['published'], str):
                        item['published'] = datetime.now()
                except Exception as e:
                    logger.warning(f"Failed to parse date for {item.get('title', 'unknown')}: {e}")
                    item['published'] = datetime.now()
            else:
                item['published'] = datetime.now()

            item['score'] = compute_score(
                url=item.get('link', ''),
                title=item.get('title', ''),
                source_id=source_id,
                published=item['published'],
                stars=item.get('stars', 0),
                upvotes=item.get('upvotes', 0)
            )

        processed = process_news(news_items)
        logger.info(f"Processed {len(processed)} unique items from {source_id}")

        breaking_count = 0
        for item in processed:
            if item.get('impact', 0) >= 4:
                breaking_count += 1

        if breaking_count > 0:
            logger.info(f"Found {breaking_count} breaking news items")
            await send_breaking_news()

        return len(processed)
    except Exception as e:
        logger.error(f"Error processing {source_id} results: {e}")
        import traceback
        traceback.print_exc()
        return 0


def schedule_source(source_id, config):
    source_type = config.get('type')
    url = config.get('url')
    interval_minutes = config.get('interval', 15)
    lang = config.get('lang', 'en')

    if not source_type or not url:
        logger.warning(f"Skipping source {source_id}: missing type or url")
        return

    if source_type not in FETCHER_CLASSES:
        logger.warning(f"Skipping source {source_id}: unknown type {source_type}")
        return

    fetcher_class = FETCHER_CLASSES[source_type]
    fetcher = fetcher_class(source_id, url, lang)

    job = scheduler.add_job(
        process_fetcher_results,
        'interval',
        args=[source_id, fetcher],
        seconds=30,  # For testing, run every 30 seconds
        id=f"fetch_{source_id}",
        replace_existing=True
    )

    logger.info(f"Scheduled {source_id} ({source_type}) to run every 30 seconds")

    add_source(source_id, f"{source_id} ({lang})")


# Initialize and schedule all jobs
async def init_scheduler():
    logger.info("Initializing scheduler")

    init_db()

    config = load_config()

    for source_id, source_config in config.items():
        schedule_source(source_id, source_config)

    scheduler.add_job(
        send_digest,
        CronTrigger(hour=7, minute=30, timezone=timezone('Europe/Kiev')),
        id="daily_digest",
        replace_existing=True
    )
    logger.info("Scheduled daily digest at 07:30 Kyiv time")

    scheduler.start()
    logger.info("Scheduler started")

    # For testing, add immediate run jobs
    for source_id, source_config in config.items():
        source_type = source_config.get('type')
        url = source_config.get('url')
        lang = source_config.get('lang', 'en')

        if source_type in FETCHER_CLASSES:
            fetcher_class = FETCHER_CLASSES[source_type]
            fetcher = fetcher_class(source_id, url, lang)
            logger.info(f"Running immediate fetch for {source_id}...")
            await process_fetcher_results(source_id, fetcher)


# Main function to run the scheduler
async def run_scheduler():
    logger.info("Starting scheduler test run")
    await init_scheduler()

    try:
        logger.info("Scheduler running. Press Ctrl+C to exit.")
        # Run for a test period (2 minutes)
        for i in range(4):
            logger.info(f"Running... {i + 1}/4 (30 seconds)")
            await asyncio.sleep(30)
        logger.info("Test run completed")
    except (KeyboardInterrupt, SystemExit):
        logger.info("Shutting down scheduler")
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(run_scheduler())