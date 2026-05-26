import os
import json
import re
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from pytz import timezone
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.fetchers.rss import RSSFetcher
from app.fetchers.github import GitHubTrendingFetcher
from app.fetchers.taaft import TAAFTFetcher
from app.db import init_db, add_source, get_connection, mark_as_sent, get_news_reactions, is_source_active
from app.summarizer import process_news
from app.ranker import compute_score
from app.common import logger, get_bot, clean_html
from app.llm_processor import ensure_russian_text, detect_language

current_dir = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(current_dir, 'fetchers', 'Config', 'config.json')

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


scheduler = AsyncIOScheduler(timezone=timezone('Europe/Kiev'))

FETCHER_CLASSES = {
    'rss': RSSFetcher,
    'scrap': GitHubTrendingFetcher,
    'api': TAAFTFetcher
}

def create_reaction_keyboard(news_id):
    """Создает клавиатуру с кнопками лайк/дизлайк для новости"""
    reactions = get_news_reactions(news_id)
    likes = 0
    dislikes = 0

    for r_type, count in reactions:
        if r_type == 'like':
            likes = count
        elif r_type == 'dislike':
            dislikes = count

    buttons = [
        [
            InlineKeyboardButton(text=f"👍 {likes}", callback_data=f"reaction:{news_id}:like"),
            InlineKeyboardButton(text=f"👎 {dislikes}", callback_data=f"reaction:{news_id}:dislike")
        ]
    ]
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard

def create_reaction_keyboard_alt(news_id):
    """Альтернативный способ создания клавиатуры с кнопками реакций"""
    reactions = get_news_reactions(news_id)
    likes = 0
    dislikes = 0

    for r_type, count in reactions:
        if r_type == 'like':
            likes = count
        elif r_type == 'dislike':
            dislikes = count

    builder = InlineKeyboardBuilder()
    builder.button(text=f"👍 {likes}", callback_data=f"reaction:{news_id}:like")
    builder.button(text=f"👎 {dislikes}", callback_data=f"reaction:{news_id}:dislike")
    builder.adjust(2)
    return builder.as_markup()


def format_news_item(news):
    """Универсальное форматирование новостей с полной очисткой служебных данных"""
    try:
        news_id = news[0]
        url = news[1]
        title = news[2]
        source_id = news[3] if len(news) > 3 else "unknown"

        title = clean_html(title)

        patterns_to_remove = [
            r'Статья\s+https?://\S+',
            r'Комментарии\s+https?://\S+',
            r'Очки:\s*\d+\s*#\s*Комментарии:\s*\d+',
            r'url статьи:',
            r'source=\w+(?:link|slink)&sk=\w+',
            r'link&sk=\w+',
            r'источник:',
            r'\[\S+\]$'
        ]

        for pattern in patterns_to_remove:
            title = re.sub(pattern, '', title).strip()

        title = re.sub(r'https?://\S+', '', title).strip()
        title = re.sub(r'com\.\.\.', '', title).strip()
        title = re.sub(r'com …', '', title).strip()
        title = re.sub(r'\s+', ' ', title).strip()
        impact = 1
        if len(news) > 6:
            impact = news[6]

        summary = ""
        if len(news) > 7:
            summary = news[7]
            summary = clean_html(summary)
            for pattern in patterns_to_remove:
                summary = re.sub(pattern, '', summary).strip()

            summary = re.sub(r'https?://\S+', '', summary).strip()

            summary = re.sub(r'\s+', ' ', summary).strip()

        stars = "★" * impact

        if not summary or summary == title:
            formatted_message = f"{stars} {title}\n\n[Читать подробнее]({url})"
        else:
            formatted_message = f"{stars} {title}\n\n{summary}\n\n[Читать подробнее]({url})"

        return formatted_message, news_id

    except Exception as e:
        from app.common import logger
        logger.error(f"Error in format_news_item: {e}, news: {news[0] if len(news) > 0 else 'unknown'}")

        if len(news) > 2:
            title = clean_html(news[2]) if news[2] else "Без заголовка"
            url = news[1] if len(news) > 1 else ""
            news_id = news[0]
            return f"{title}\n\n[Читать подробнее]({url})", news_id
        else:
            return "Новость без заголовка", news[0] if len(news) > 0 else 0


# Функция для отправки новости
async def send_news_item(news):
    bot = get_bot()
    if not bot:
        logger.error("Bot instance not available. Cannot send message.")
        return False

    from app.common import CHANNEL_ID

    try:
        # Проверяем, нужен ли принудительный перевод заголовка перед форматированием
        news_id = news[0]
        title = news[2] if len(news) > 2 else ""

        title_lang = detect_language(title)
        if title_lang != "ru" and len(title) > 10:
            logger.info(f"Принудительный перевод заголовка перед отправкой: {title[:50]}...")
            try:
                translated_title = await ensure_russian_text(title)

                # Обновляем заголовок в базе данных
                with get_connection() as conn:
                    conn.execute("UPDATE news_items SET title = ? WHERE id = ?", (translated_title, news_id))
                    conn.commit()

                # Обновляем заголовок в объекте новости для форматирования
                news = list(news)
                news[2] = translated_title
                news = tuple(news)

                logger.info(f"Заголовок переведен и обновлен: {translated_title[:50]}...")
            except Exception as e:
                logger.error(f"Ошибка при переводе заголовка: {e}")

        formatted_message, news_id = format_news_item(news)
    except Exception as format_error:
        logger.error(f"Error formatting news item: {format_error}")
        # Пытаемся хотя бы извлечь ID новости для пометки как отправленной
        if isinstance(news, (list, tuple)) and len(news) > 0:
            news_id = news[0]
            formatted_message = "Ошибка форматирования новости. Пожалуйста, проверьте логи."
        else:
            logger.error("Cannot extract news_id from malformed news item")
            return False

    try:
        # Пробуем создать клавиатуру
        try:
            keyboard = create_reaction_keyboard(news_id)
        except Exception as keyboard_error:
            # Если основной способ не работает, пробуем альтернативный
            logger.warning(f"Failed to create keyboard using primary method: {keyboard_error}")
            try:
                keyboard = create_reaction_keyboard_alt(news_id)
            except Exception as alt_error:
                # Если ни один способ не работает, отправляем без клавиатуры
                logger.error(f"Failed to create keyboard using alternative method: {alt_error}")
                keyboard = None

        from aiogram.enums import ParseMode

        # Дополнительно проверяем наличие непарсящихся символов или проблемных тегов
        message = await bot.send_message(
            chat_id=CHANNEL_ID,
            text=formatted_message,
            parse_mode=ParseMode.MARKDOWN,
            disable_web_page_preview=False,
            reply_markup=keyboard  # Может быть None, если не удалось создать
        )
        # Сохраняем ID сообщения вместе с отметкой о отправке
        mark_as_sent(news_id, message.message_id)

        logger.info(f"Sent news item {news_id} to channel {CHANNEL_ID} with message_id {message.message_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to send news item {news_id}: {e}")
        # Пытаемся отправить сообщение с отключением форматирования, если произошла ошибка
        if "can't parse entities" in str(e) or "Bad Request" in str(e):
            try:
                logger.warning(f"Failed to send with formatting, trying without formatting")
                # Если ошибка парсинга Markdown, попробуем отправить без форматирования
                title = clean_html(news[2]) if len(news) > 2 and news[2] else "Без заголовка"
                url = news[1] if len(news) > 1 else ""
                message = await bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=f"{title}\n\n{url}",
                    parse_mode=None,
                    disable_web_page_preview=False
                )
                mark_as_sent(news_id, message.message_id)
                logger.info(f"Sent news item {news_id} without formatting")
                return True
            except Exception as backup_error:
                logger.error(f"Failed to send even without formatting: {backup_error}")
                return False
        return False


# Функция для отправки важных новостей
async def send_breaking_news():
    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM news_items 
            WHERE sent = 0 AND impact >= 4 
            ORDER BY score DESC, published DESC
            LIMIT 30  -- Added limit for safety
            """
        )
        breaking_news = cursor.fetchall()

    if not breaking_news:
        logger.info("No breaking news to send")
        return 0

    sent_count = 0
    for news in breaking_news:
        try:
            success = await send_news_item(news)
            if success:
                sent_count += 1
                # Add a small sleep between messages
                import asyncio
                await asyncio.sleep(1)  # 1 second delay to avoid flood
        except Exception as e:
            logger.error(f"Error sending breaking news item (id {news[0]}): {e}")
            continue

    logger.info(f"Sent {sent_count} breaking news items")
    return sent_count


# Функция для отправки дайджеста
async def send_digest():
    from app.common import CHANNEL_ID
    bot = get_bot()
    if not bot:
        logger.error("Bot instance not available. Cannot send digest.")
        return 0

    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT * FROM news_items 
            WHERE sent = 0 AND impact < 4 
            ORDER BY impact DESC, score DESC, published DESC
            LIMIT 50  -- Added limit for safety
            """
        )
        digest_news = cursor.fetchall()

    if not digest_news:
        logger.info("No unsent news for digest")
        return 0

    current_date = datetime.now().strftime("%d.%m.%Y")
    header = f"📰 *AI News Digest ({current_date})*\n\n"

    news_by_impact = {}
    for news in digest_news:
        # Считаем, что impact может быть в разных позициях в зависимости от версии базы данных
        if len(news) >= 11:  # с полем summary_lang
            impact = news[6]  # impact is at index 6
        else:
            impact = news[6]  # тоже на 6, но для совместимости явно указываем

        if impact not in news_by_impact:
            news_by_impact[impact] = []
        news_by_impact[impact].append(news)

    digest_content = header
    for impact in sorted(news_by_impact.keys(), reverse=True):
        news_items = news_by_impact[impact]
        for news in news_items:
            # Проверяем и при необходимости переводим заголовок
            news_id = news[0]
            title = news[2]
            title_lang = detect_language(title)

            if title_lang != "ru" and len(title) > 10:
                try:
                    title = await ensure_russian_text(title)
                    # Обновляем заголовок в базе данных
                    with get_connection() as conn:
                        conn.execute("UPDATE news_items SET title = ? WHERE id = ?", (title, news_id))
                        conn.commit()
                except Exception as e:
                    logger.error(f"Error translating title for digest: {e}")

            # Очищаем заголовок от HTML
            title = clean_html(title)
            url = news[1]  # URL
            stars = "★" * impact
            digest_content += f"{stars} {title} — [Link]({url})\n\n"

    try:
        from aiogram.enums import ParseMode
        # Split long digest into multiple messages if needed (Telegram limit ~4000 chars)
        if len(digest_content) > 3900:
            chunks = []
            current_chunk = header
            lines = digest_content.split("\n\n")[1:]  # Skip header

            for line in lines:
                if len(current_chunk) + len(line) + 4 > 3900:
                    chunks.append(current_chunk)
                    current_chunk = header + "*(продолжение)*\n\n" + line + "\n\n"
                else:
                    current_chunk += line + "\n\n"

            if current_chunk:
                chunks.append(current_chunk)

            for i, chunk in enumerate(chunks):
                await bot.send_message(
                    chat_id=CHANNEL_ID,
                    text=chunk,
                    parse_mode=ParseMode.MARKDOWN,
                    disable_web_page_preview=True
                )
                # Add delay between messages
                import asyncio
                await asyncio.sleep(1)
        else:
            await bot.send_message(
                chat_id=CHANNEL_ID,
                text=digest_content,
                parse_mode=ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )

        for news in digest_news:
            news_id = news[0]
            mark_as_sent(news_id)

        logger.info(f"Sent digest with {len(digest_news)} news items to channel {CHANNEL_ID}")
        return len(digest_news)
    except Exception as e:
        logger.error(f"Failed to send digest: {e}")
        return 0


# Process news items from a fetcher
async def process_fetcher_results(source_id, fetcher):
    # Проверяем активность источника перед обработкой
    if not is_source_active(source_id):
        logger.info(f"Skipping inactive source: {source_id}")
        return 0

    logger.info(f"Processing results from {source_id}")
    try:
        news_items = await fetcher.fetch()
        logger.info(f"Fetched {len(news_items)} items from {source_id}")

        if not news_items:
            logger.info(f"No news items fetched from {source_id}")
            return 0

        # Log the first item for debugging
        if news_items:
            logger.info(f"Sample item from {source_id}: {news_items[0].get('title')}")

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

        # Add more debug logging
        logger.info(f"Sending {len(news_items)} items to process_news from {source_id}")

        # Process the items
        processed = await process_news(news_items)
        logger.info(f"Processed {len(processed)} unique items from {source_id}")

        breaking_count = 0
        for item in processed:
            if item.get('impact', 0) >= 4:
                breaking_count += 1
                logger.info(f"Found breaking news: {item.get('title')} (impact: {item.get('impact')})")

        if breaking_count > 0:
            logger.info(f"Found {breaking_count} breaking news items, sending now...")
            try:
                sent_count = await send_breaking_news()
                logger.info(f"Successfully sent {sent_count} breaking news items")
            except Exception as e:
                logger.error(f"Error sending breaking news: {e}")
                import traceback
                traceback.print_exc()

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
        minutes=interval_minutes,
        id=f"fetch_{source_id}",
        replace_existing=True
    )

    logger.info(f"Scheduled {source_id} ({source_type}) to run every {interval_minutes} minutes")

    add_source(source_id, f"{source_id} ({lang})")


async def process_single_source(source_id):
    """Обрабатывает один указанный источник независимо от расписания"""

    config = load_config()
    if source_id not in config:
        return f"Source {source_id} not found in config"

    # Проверяем активность даже для ручного запуска
    if not is_source_active(source_id):
        return f"Source {source_id} is inactive. Enable it with /toggle {source_id} first"

    source_config = config[source_id]
    source_type = source_config.get('type')
    url = source_config.get('url')
    lang = source_config.get('lang', 'en')

    if source_type not in FETCHER_CLASSES:
        return f"Unknown source type: {source_type}"

    fetcher_class = FETCHER_CLASSES[source_type]
    fetcher = fetcher_class(source_id, url, lang)

    processed_count = await process_fetcher_results(source_id, fetcher)
    return f"Processed {processed_count} news items from {source_id}"


# Initialize and schedule all jobs
async def init_scheduler():
    logger.info("Initializing scheduler")

    init_db()
    config = load_config()

    for source_id, source_config in config.items():
        add_source(source_id, f"{source_id} ({source_config.get('lang', 'en')})")

    for source_id, source_config in config.items():
        if is_source_active(source_id):
            schedule_source(source_id, source_config)
        else:
            logger.info(f"Source {source_id} is inactive, skipping scheduler setup")

    # Add job for sending digest at specific time (7:30 Kyiv time)
    scheduler.add_job(
        send_digest,
        CronTrigger(hour=7, minute=30, timezone=timezone('Europe/Kiev')),
        id="daily_digest",
        replace_existing=True
    )
    logger.info("Scheduled daily digest at 07:30 Kyiv time")

    # Check for breaking news every hour
    scheduler.add_job(
        send_breaking_news,
        'interval',
        hours=1,
        id="hourly_breaking_news",
        replace_existing=True
    )
    logger.info("Scheduled hourly check for breaking news")

    scheduler.start()
    logger.info("Scheduler started")