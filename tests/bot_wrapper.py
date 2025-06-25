import os
import sys

from app.db import get_connection, mark_as_sent, init_db

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
app_dir = os.path.join(parent_dir, 'app')
sys.path.insert(0, app_dir)  # Добавляем app директорию в путь

import os
from dotenv import load_dotenv

current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
app_dir = os.path.join(parent_dir, 'app')
env_path = os.path.join(parent_dir, "keys", "keys.env")

load_dotenv(dotenv_path=env_path)

init_db()

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("TG_CHANNEL_ID")

async def send_breaking_news():
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM news_items 
            WHERE sent = 0 AND impact >= 4 
            ORDER BY score DESC, published DESC
            """
        )
        breaking_news = cursor.fetchall()

    sent_count = 0
    for news in breaking_news:
        # Здесь нам не нужна полная реализация send_news_item
        # Мы просто отмечаем новости как отправленные
        news_id = news[0]
        mark_as_sent(news_id)
        print(f"Would send news item {news_id}")
        sent_count += 1

    return sent_count


async def send_digest():
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM news_items 
            WHERE sent = 0 AND impact < 4 
            ORDER BY impact DESC, score DESC, published DESC
            """
        )
        digest_news = cursor.fetchall()

    if not digest_news:
        print("No unsent news for digest")
        return 0

    # Просто отмечаем как отправленные
    for news in digest_news:
        news_id = news[0]
        mark_as_sent(news_id)

    print(f"Would send digest with {len(digest_news)} news items")
    return len(digest_news)