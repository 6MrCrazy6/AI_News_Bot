import os
import json
import re
import asyncio
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode

from app.fetchers.rss import RSSFetcher
from app.fetchers.github import GitHubTrendingFetcher
from app.fetchers.taaft import TAAFTFetcher
from app.fetchers.json_feed import JSONFeedFetcher
from app.db import init_db, add_source, get_connection, mark_as_sent, get_news_reactions, is_source_active
from app.summarizer import process_news
from app.ranker import compute_score
from app.common import logger, get_bot, clean_html
from app.llm_processor import ensure_russian_text, detect_language

current_dir = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(current_dir, 'fetchers', 'Config', 'config.json')

def load_config():
    try:
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to load config: {e}")
        return {}

scheduler = AsyncIOScheduler(timezone=timezone('Europe/Kiev'))

FETCHER_CLASSES = {
    'rss': RSSFetcher,
    'scrap': GitHubTrendingFetcher,
    'api': TAAFTFetcher,
    'json_feed': JSONFeedFetcher
}

def create_reaction_keyboard(news_id):
    reactions = get_news_reactions(news_id)
    likes = 0
    dislikes = 0
    for r in reactions:
        if r['reaction_type'] == 'like': likes = r['count']
        elif r['reaction_type'] == 'dislike': dislikes = r['count']

    buttons = [[
        InlineKeyboardButton(text=f"👍 {likes}", callback_data=f"reaction:{news_id}:like"),
        InlineKeyboardButton(text=f"👎 {dislikes}", callback_data=f"reaction:{news_id}:dislike")
    ]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def format_news_item(news):
    try:
        # news is a sqlite3.Row or dict
        news_id = news['id']
        url = news['url']
        title = clean_html(news['title'])
        impact = news['impact']
        summary = clean_html(news['summary'] or "")

        stars = "★" * impact
        if not summary or summary == title:
            formatted_message = f"{stars} *{title}*\n\n[Читать подробнее]({url})"
        else:
            formatted_message = f"{stars} *{title}*\n\n{summary}\n\n[Читать подробнее]({url})"
        return formatted_message, news_id
    except Exception as e:
        logger.error(f"Error in format_news_item: {e}")
        return f"Новость: {news.get('title', 'Без названия')}", news.get('id', 0)

async def send_news_item(news):
    bot = get_bot()
    if not bot: return False
    from app.common import CHANNEL_ID

    try:
        formatted_message, news_id = format_news_item(news)
        keyboard = create_reaction_keyboard(news_id)
        
        message = await bot.send_message(
            chat_id=CHANNEL_ID,
            text=formatted_message,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
        mark_as_sent(news_id, message.message_id)
        return True
    except Exception as e:
        logger.error(f"Failed to send news item: {e}")
        return False

async def send_breaking_news():
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM news_items WHERE sent = 0 AND impact >= 4 ORDER BY score DESC LIMIT 20")
        breaking_news = cursor.fetchall()

    sent_count = 0
    for news in breaking_news:
        if await send_news_item(news):
            sent_count += 1
            await asyncio.sleep(1)
    return sent_count

async def send_digest():
    bot = get_bot()
    if not bot: return 0
    from app.common import CHANNEL_ID

    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM news_items WHERE sent = 0 AND impact < 4 ORDER BY impact DESC, score DESC LIMIT 40")
        digest_news = cursor.fetchall()

    if not digest_news: return 0

    current_date = datetime.now().strftime("%d.%m.%Y")
    header = f"📰 *AI News Digest ({current_date})*\n\n"
    
    messages = []
    current_content = header
    
    for news in digest_news:
        title = clean_html(news['title'])
        url = news['url']
        stars = "★" * news['impact']
        entry = f"{stars} {title} — [Link]({url})\n\n"
        
        if len(current_content) + len(entry) > 3900:
            messages.append(current_content)
            current_content = header + "*(продолжение)*\n\n" + entry
        else:
            current_content += entry
    
    if current_content:
        messages.append(current_content)

    for msg in messages:
        await bot.send_message(chat_id=CHANNEL_ID, text=msg, parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        await asyncio.sleep(1)
    
    # Mark all as sent
    for news in digest_news:
        mark_as_sent(news['id'])
    
    return len(digest_news)

async def process_source(source_id, config):
    try:
        fetcher_class = FETCHER_CLASSES.get(config['type'])
        if not fetcher_class: return
        
        fetcher = fetcher_class(source_id, config['url'], config.get('lang', 'en'))
        raw_news = await fetcher.fetch()
        if not raw_news: return
        
        processed = await process_news(raw_news)
        logger.info(f"Source {source_id}: processed {len(processed)} new items")
        
        # Immediate send for breaking news
        await send_breaking_news()
    except Exception as e:
        logger.error(f"Error processing source {source_id}: {e}")

async def run_all_sources():
    config = load_config()
    tasks = []
    for s_id, s_config in config.items():
        if is_source_active(s_id):
            tasks.append(process_source(s_id, s_config))
    if tasks:
        await asyncio.gather(*tasks)

async def init_scheduler():
    init_db()
    config = load_config()
    for s_id, s_config in config.items():
        add_source(s_id, s_id, weight=s_config.get('weight', 1))
        interval = s_config.get('interval', 60)
        scheduler.add_job(process_source, 'interval', minutes=interval, args=[s_id, s_config])
    
    # Daily digest at 08:00
    scheduler.add_job(send_digest, CronTrigger(hour=8, minute=0))
    scheduler.start()
    logger.info("Scheduler started")

if __name__ == "__main__":
    async def main():
        from app.bot import main as bot_main
        await init_scheduler()
        await bot_main()
    asyncio.run(main())
