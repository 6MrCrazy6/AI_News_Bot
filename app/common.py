import logging
import os
from dotenv import load_dotenv
from bs4 import BeautifulSoup
import html
import re

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
env_path = os.path.join(project_root, "keys", "keys.env")

load_dotenv(dotenv_path=env_path)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHANNEL_ID = os.getenv("TG_CHANNEL_ID")

if not TOKEN:
    logger.warning("TELEGRAM_TOKEN environment variable is not set")

if not CHANNEL_ID:
    logger.warning("TG_CHANNEL_ID environment variable is not set")

bot_instance = None


def set_bot(bot):
    global bot_instance
    bot_instance = bot


def get_bot():
    return bot_instance


def clean_html(text):
    """Полная очистка текста от HTML-тегов, сущностей и служебных меток"""
    if not text:
        return ""

    soup = BeautifulSoup(text, "html.parser")
    clean_text = soup.get_text(separator=" ", strip=True)

    clean_text = html.unescape(clean_text)

    clean_text = re.sub(r'url статьи:', '', clean_text)
    clean_text = re.sub(r'URL:', '', clean_text)
    clean_text = re.sub(r'Комментарии URL:', '', clean_text)
    clean_text = re.sub(r'<a href\s*=\s*["\'][^"\']*["\'].*?>', '', clean_text)
    clean_text = re.sub(r'</a>', '', clean_text)

    clean_text = re.sub(r'\s+', ' ', clean_text).strip()

    return clean_text