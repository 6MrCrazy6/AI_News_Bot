import asyncio
import os
import scheduler
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.enums import ParseMode
from dotenv import load_dotenv

from db import get_connection, init_db, add_reaction, get_news_reactions
from db import get_source_reaction_stats, get_news_by_message_id
from common import TOKEN, CHANNEL_ID, logger, set_bot

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
env_path = os.path.join(project_root, "keys", "keys.env")

load_dotenv(dotenv_path=env_path)

init_db()

if not TOKEN:
    raise ValueError("TELEGRAM_TOKEN environment variable is not set")

if not CHANNEL_ID:
    raise ValueError("TG_CHANNEL_ID environment variable is not set")

admin_router = Router()
bot = Bot(token=TOKEN)
dp = Dispatcher()

set_bot(bot)

dp.include_router(admin_router)


# Admin commands
@admin_router.message(Command("stats"))
async def cmd_stats(message: Message):
    yesterday = datetime.now() - timedelta(days=1)
    yesterday_str = yesterday.strftime("%Y-%m-%d %H:%M:%S")

    last_week = datetime.now() - timedelta(days=7)
    last_week_str = last_week.strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT COUNT(*) FROM news_items WHERE processed_at >= ?",
            (yesterday_str,)
        )
        daily_count = cursor.fetchone()[0]

        cursor = conn.execute(
            "SELECT COUNT(*) FROM news_items WHERE processed_at >= ?",
            (last_week_str,)
        )
        weekly_count = cursor.fetchone()[0]

        cursor = conn.execute(
            "SELECT COUNT(*) FROM news_items WHERE impact >= 4 AND processed_at >= ?",
            (last_week_str,)
        )
        breaking_count = cursor.fetchone()[0]

        cursor = conn.execute(
            """
            SELECT source_id, COUNT(*) 
            FROM news_items 
            WHERE processed_at >= ? 
            GROUP BY source_id
            """,
            (last_week_str,)
        )
        sources_stats = cursor.fetchall()

    # Format stats message
    stats_message = (
        f"📊 *News Stats*\n\n"
        f"Last 24 hours: {daily_count} news items\n"
        f"Last 7 days: {weekly_count} news items\n"
        f"Breaking news (last 7 days): {breaking_count} items\n\n"
        f"*By source (last 7 days):*\n"
    )

    for source_id, count in sources_stats:
        stats_message += f"- {source_id}: {count} items\n"

    await message.answer(stats_message, parse_mode=ParseMode.MARKDOWN)


@admin_router.message(Command("toggle"))
async def cmd_toggle_source(message: Message):
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Usage: /toggle source_id")
        return

    source_id = parts[1]

    with get_connection() as conn:
        cursor = conn.execute("SELECT active FROM sources WHERE id = ?", (source_id,))
        source = cursor.fetchone()

        if not source:
            await message.answer(f"Source {source_id} not found")
            return

        new_status = 1 - source[0]
        conn.execute("UPDATE sources SET active = ? WHERE id = ?", (new_status, source_id))
        conn.commit()

    config = scheduler.load_config()
    if source_id in config:
        job_id = f"fetch_{source_id}"

        if new_status == 1:
            scheduler.schedule_source(source_id, config[source_id])
            await message.answer(f"Source {source_id} enabled and scheduled")
        else:
            try:
                scheduler.scheduler.remove_job(job_id)
                await message.answer(f"Source {source_id} disabled and unscheduled")
            except Exception as e:
                logger.error(f"Error removing job: {e}")
                await message.answer(f"Source {source_id} disabled, but scheduler error occurred")
    else:
        status_text = "enabled" if new_status == 1 else "disabled"
        await message.answer(f"Source {source_id} {status_text}, but not found in config")


@admin_router.message(Command("process_source"))
async def cmd_process_source(message: Message):
    """Обрабатывает указанный источник вручную"""
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Usage: /process_source source_id")
        return

    source_id = parts[1]
    result = await scheduler.process_single_source(source_id)
    await message.answer(result)


@admin_router.message(Command("digest"))
async def cmd_digest(message: Message):
    parts = message.text.split()
    if len(parts) != 2 or parts[1] != "now":
        await message.answer("Usage: /digest now")
        return

    sent_count = await scheduler.send_digest()
    await message.answer(f"Sent digest with {sent_count} news items")


@admin_router.message(Command("breaking"))
async def cmd_breaking(message: Message):
    sent_count = await scheduler.send_breaking_news()
    await message.answer(f"Sent {sent_count} breaking news items")



# Health check command
@admin_router.message(Command("healthz"))
async def cmd_healthz(message: Message):
    with get_connection() as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM news_items WHERE sent = 0")
        queue_count = cursor.fetchone()[0]

    await message.answer(f"OK. Queue size: {queue_count}")


# Команда для статистики по источникам
@admin_router.message(Command("source_stats"))
async def cmd_source_reactions_stats(message: Message):
    parts = message.text.split()
    period_days = 30  # По умолчанию за 30 дней

    if len(parts) > 1 and parts[1].isdigit():
        period_days = int(parts[1])

    stats = get_source_reaction_stats(period_days)

    if not stats:
        await message.answer(f"Нет данных о реакциях по источникам за последние {period_days} дней")
        return

    stats_message = f"📊 *Статистика источников за {period_days} дней*\n\n"

    for source_id, news_count, likes, dislikes in stats:
        if likes > 0 or dislikes > 0 or news_count > 0:  # Показываем только если есть активность
            total = likes + dislikes
            like_percent = int((likes / total) * 100) if total > 0 else 0

            engagement_rate = round((total / news_count) * 100, 1) if news_count > 0 else 0

            stats_message += (
                f"*{source_id}*\n"
                f"• Новостей: {news_count}\n"
                f"• Реакций: {total} (👍 {likes}, 👎 {dislikes})\n"
                f"• Рейтинг: {like_percent}% положительных\n"
                f"• Вовлеченность: {engagement_rate}%\n\n"
            )

    await message.answer(stats_message, parse_mode=ParseMode.MARKDOWN)


# Новая команда для топ-50 новостей с наибольшим числом лайков
@admin_router.message(Command("top_news"))
async def cmd_top_news(message: Message):
    parts = message.text.split()
    period_days = 30  # По умолчанию за 30 дней
    limit = 10  # По умолчанию топ-10

    if len(parts) > 1 and parts[1].isdigit():
        period_days = int(parts[1])

    if len(parts) > 2 and parts[2].isdigit():
        limit = min(50, int(parts[2]))  # Ограничиваем максимум 50 записей

    period_date = datetime.now() - timedelta(days=period_days)
    period_str = period_date.strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT 
                n.id, 
                n.title, 
                n.source_id,
                n.url,
                (SELECT COUNT(*) FROM news_reactions WHERE news_id = n.id AND reaction_type = 'like') as likes,
                (SELECT COUNT(*) FROM news_reactions WHERE news_id = n.id AND reaction_type = 'dislike') as dislikes
            FROM 
                news_items n
            WHERE
                n.processed_at >= ?
            ORDER BY
                likes DESC, dislikes ASC
            LIMIT ?
            """,
            (period_str, limit)
        )
        top_news = cursor.fetchall()

    if not top_news:
        await message.answer(f"Нет данных о популярных новостях за последние {period_days} дней")
        return

    stats_message = f"🏆 *Топ-{limit} новостей за {period_days} дней*\n\n"

    for i, (news_id, title, source_id, url, likes, dislikes) in enumerate(top_news, 1):
        total = likes + dislikes
        like_percent = int((likes / total) * 100) if total > 0 else 0

        stats_message += (
            f"{i}. *{title}*\n"
            f"• 👍 {likes} / 👎 {dislikes} ({like_percent}% положительных)\n"
            f"• [Подробнее]({url})\n\n"
        )

    await message.answer(stats_message, parse_mode=ParseMode.MARKDOWN)


# Команда для статистики языка новостей
@admin_router.message(Command("language_stats"))
async def cmd_language_stats(message: Message):
    period_days = 7

    parts = message.text.split()
    if len(parts) > 1 and parts[1].isdigit():
        period_days = int(parts[1])

    period_date = datetime.now() - timedelta(days=period_days)
    period_str = period_date.strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        # Получаем общее количество новостей
        cursor = conn.execute(
            "SELECT COUNT(*) FROM news_items WHERE processed_at >= ?",
            (period_str,)
        )
        total_count = cursor.fetchone()[0]

        # Проверяем, есть ли у нас поля для отслеживания языка
        cursor = conn.execute("PRAGMA table_info(news_items)")
        columns = [col[1] for col in cursor.fetchall()]

        if "summary_lang" not in columns:
            # Если нет поля для языка, добавляем его
            try:
                logger.info("Adding summary_lang column to news_items table")
                conn.execute("ALTER TABLE news_items ADD COLUMN summary_lang TEXT")
                conn.commit()

                # Базовая статистика после добавления
                stats_message = (
                    f"📊 *Статистика языка новостей за {period_days} дней*\n\n"
                    f"Всего новостей: {total_count}\n\n"
                    f"Поле 'summary_lang' успешно добавлено в таблицу news_items.\n"
                    f"Статистика языка будет доступна после обработки новых новостей."
                )
            except Exception as e:
                stats_message = (
                    f"📊 *Статистика языка новостей*\n\n"
                    f"Ошибка при добавлении поля 'summary_lang': {e}\n"
                    f"Обратитесь к администратору системы."
                )
        else:
            # Если поле есть, получаем статистику
            cursor = conn.execute(
                """
                SELECT 
                    summary_lang, 
                    COUNT(*) as count 
                FROM 
                    news_items 
                WHERE 
                    processed_at >= ? 
                    AND summary_lang IS NOT NULL
                GROUP BY 
                    summary_lang
                ORDER BY 
                    count DESC
                """,
                (period_str,)
            )
            lang_stats = cursor.fetchall()

            stats_message = f"📊 *Статистика языка новостей за {period_days} дней*\n\n"
            stats_message += f"Всего новостей: {total_count}\n\n"

            total_with_lang = sum(count for _, count in lang_stats)

            for lang, count in lang_stats:
                percent = round((count / total_count) * 100, 1) if total_count > 0 else 0
                lang_name = "Русский" if lang == "ru" else "Английский" if lang == "en" else lang
                stats_message += f"• {lang_name}: {count} ({percent}%)\n"

            if total_with_lang < total_count:
                unknown = total_count - total_with_lang
                unknown_percent = round((unknown / total_count) * 100, 1)
                stats_message += f"• Нет данных о языке: {unknown} ({unknown_percent}%)\n"

    await message.answer(stats_message, parse_mode=ParseMode.MARKDOWN)


# Добавьте эту команду в файл bot.py в секцию admin_router:

@admin_router.message(Command("list_sources"))
async def cmd_list_sources(message: Message):
    """Показывает список всех источников новостей с их статусом"""
    config = scheduler.load_config()

    # Получаем статус каждого источника (включен/отключен)
    with get_connection() as conn:
        source_status = {}
        cursor = conn.execute("SELECT id, active FROM sources")
        for source_id, active in cursor.fetchall():
            source_status[source_id] = bool(active)

    # Формируем сообщение со списком источников
    sources_message = "📋 *Список источников новостей*\n\n"

    # Группируем источники по языку для удобства
    en_sources = []
    ru_sources = []
    other_sources = []

    for source_id, source_config in config.items():
        # Получаем тип и язык источника
        source_type = source_config.get('type', 'unknown')
        lang = source_config.get('lang', 'en')
        interval = source_config.get('interval', 15)

        status = "✅" if source_status.get(source_id, True) else "❌"

        source_info = f"{status} `{source_id}` - {source_type} (обновление: {interval} мин)"

        if lang == "ru":
            ru_sources.append(source_info)
        elif lang == "en":
            en_sources.append(source_info)
        else:
            other_sources.append(source_info)

    if en_sources:
        sources_message += "*Английские источники:*\n"
        sources_message += "\n".join(en_sources)
        sources_message += "\n\n"

    if ru_sources:
        sources_message += "*Русские источники:*\n"
        sources_message += "\n".join(ru_sources)
        sources_message += "\n\n"

    if other_sources:
        sources_message += "*Другие источники:*\n"
        sources_message += "\n".join(other_sources)
        sources_message += "\n\n"

    sources_message += "*Управление источниками:*\n"
    sources_message += "• `/toggle ID` - включить/отключить источник\n"
    sources_message += "• `/process_source ID` - обработать один источник\n"

    await message.answer(sources_message, parse_mode=ParseMode.MARKDOWN)


# Также добавьте команду для проверки статистики по источникам:
@admin_router.message(Command("source_info"))
async def cmd_source_info(message: Message):
    """Показывает статистику по одному источнику"""
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Использование: /source_info ID_источника")
        return

    source_id = parts[1]

    config = scheduler.load_config()
    if source_id not in config:
        await message.answer(f"Источник с ID '{source_id}' не найден в конфигурации")
        return

    source_config = config[source_id]
    source_type = source_config.get('type', 'unknown')
    lang = source_config.get('lang', 'unknown')
    interval = source_config.get('interval', 0)
    url = source_config.get('url', '')

    with get_connection() as conn:
        cursor = conn.execute("SELECT active FROM sources WHERE id = ?", (source_id,))
        source = cursor.fetchone()
        active = bool(source[0]) if source else False

        cursor = conn.execute(
            "SELECT COUNT(*) FROM news_items WHERE source_id = ?",
            (source_id,)
        )
        total_news = cursor.fetchone()[0]

        # Последние новости
        cursor = conn.execute(
            """
            SELECT title, impact, processed_at 
            FROM news_items 
            WHERE source_id = ? 
            ORDER BY processed_at DESC 
            LIMIT 5
            """,
            (source_id,)
        )
        recent_news = cursor.fetchall()

        # Статистика реакций
        cursor = conn.execute(
            """
            SELECT 
                COUNT(DISTINCT CASE WHEN r.reaction_type = 'like' THEN r.id END) as likes,
                COUNT(DISTINCT CASE WHEN r.reaction_type = 'dislike' THEN r.id END) as dislikes
            FROM 
                news_items n
            LEFT JOIN
                news_reactions r ON n.id = r.news_id
            WHERE
                n.source_id = ?
            """,
            (source_id,)
        )
        likes, dislikes = cursor.fetchone()

    # Формируем сообщение
    status = "✅ Активен" if active else "❌ Отключен"

    info_message = (
        f"📊 *Информация о источнике: {source_id}*\n\n"
        f"• Статус: {status}\n"
        f"• Тип: {source_type}\n"
        f"• Язык: {lang}\n"
        f"• Интервал обновления: {interval} минут\n"
        f"• Всего новостей: {total_news}\n"
        f"• Реакции: 👍 {likes} / 👎 {dislikes}\n\n"
    )

    if url:
        info_message += f"• URL: `{url}`\n\n"

    if recent_news:
        info_message += "*Последние новости:*\n"
        for title, impact, date in recent_news:
            stars = "★" * impact
            info_message += f"{stars} {title[:30]}{'...' if len(title) > 30 else ''}\n"
    else:
        info_message += "*Нет новостей от этого источника*\n"

    await message.answer(info_message, parse_mode=ParseMode.MARKDOWN)

@admin_router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = """
📱 *AI News Bot - Команды*

*Основные команды:*
- `/help` - Объясняет, как использовать бота и его функции
- `/stats` - Статистика новостей за последнюю неделю
- `/top_news [дней] [число]` - Топ-N популярных новостей по лайкам
- `/source_stats [дней]` - Рейтинг эффективности источников
- `/language_stats [дней]` - Статистика языков в новостях
- `/healthz` - Проверка работоспособности бота
- `/list_sources` - Выводит список всех источников новостей

*Команды администратора:*
- `/toggle [source_id]` - Включить/выключить источник новостей
- `/process_source [source_id]` - Обработать один источник вручную
- `/digest now` - Отправить дайджест новостей сейчас
- `/breaking` - Отправить важные новости сейчас
- `/reactions [дней]` - Статистика популярности новостей по реакциям
- `/source_info [source_id]` - Детальная информация по источнику
- `/db_status` - Показать статус базы данных

*Как пользоваться ботом:*
1. AI News Bot автоматически собирает и публикует новости об искусственном интеллекте и технологиях
2. Под каждой новостью есть кнопки 👍 / 👎 для оценки контента
3. Ваши оценки помогают определить, какие новости и источники интереснее
4. Новости публикуются из различных источников (RSS, API, GitHub и др.)

*Периодичность публикаций:*
- Важные новости (★★★★/★★★★★) публикуются сразу после обнаружения
- Обычные новости собираются в ежедневный дайджест (7:30 утра)
- Новости получаются из англоязычных и русскоязычных источников
- Сообщения форматируются с помощью ИИ для лучшего восприятия

Если у вас есть предложения по улучшению бота, напишите администратору.
"""

    await message.answer(help_text, parse_mode=ParseMode.MARKDOWN)

@dp.callback_query()
async def process_callback(callback_query: CallbackQuery):
    """
    Обрабатывает нажатия на кнопки реакций.
    Использует message_id для поиска новости, если данные в callback некорректны.
    """
    # Проверяем, начинается ли callback_data с 'reaction:'
    if not callback_query.data.startswith('reaction:'):
        await callback_query.answer()
        return

    try:
        # Разбираем данные из callback_data
        parts = callback_query.data.split(':')
        if len(parts) != 3:
            logger.warning(f"Invalid callback data format: {callback_query.data}")
            await callback_query.answer("Некорректный формат данных")
            return

        _, news_id_str, reaction_type = parts

        # Проверяем, что news_id - это число
        try:
            news_id = int(news_id_str)
        except ValueError:
            # Если news_id не число, пробуем найти его по message_id
            logger.warning(f"Invalid news_id format: {news_id_str}, trying to find by message_id")
            news_id = get_news_by_message_id(callback_query.message.message_id)
            if not news_id:
                logger.error(f"Could not find news_id for message_id {callback_query.message.message_id}")
                await callback_query.answer("Не удалось найти новость")
                return

        # Проверяем тип реакции
        if reaction_type not in ('like', 'dislike'):
            logger.warning(f"Invalid reaction type: {reaction_type}")
            await callback_query.answer("Некорректный тип реакции")
            return

        # Получаем информацию о пользователе
        user_id = callback_query.from_user.id
        username = callback_query.from_user.username or callback_query.from_user.first_name

        # Добавляем реакцию в базу данных
        success = add_reaction(news_id, callback_query.message.message_id, reaction_type, user_id, username)
        if not success:
            logger.warning(f"Failed to add reaction for user {user_id} on news {news_id}")
            await callback_query.answer("Не удалось сохранить вашу реакцию")
            return

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

        try:
            await bot.edit_message_reply_markup(
                chat_id=callback_query.message.chat.id,
                message_id=callback_query.message.message_id,
                reply_markup=keyboard
            )

            if reaction_type == 'like':
                await callback_query.answer("Спасибо за ваш лайк! 👍")
            else:
                await callback_query.answer("Спасибо за ваш фидбек! 👎")

        except Exception as e:
            if "Too Many Requests" in str(e) or "Flood control" in str(e):
                await callback_query.answer("Слишком много действий! Попробуйте через несколько секунд.")
            else:
                logger.error(f"Ошибка при обновлении кнопок: {e}")
                await callback_query.answer("Произошла ошибка при обработке реакции")
    except Exception as e:
        logger.error(f"Unexpected error in callback processing: {e}")
        try:
            await callback_query.answer("Произошла ошибка при обработке реакции")
        except:
            pass




async def start_services():
    logger.info("Starting scheduler")
    await scheduler.init_scheduler()

    logger.info("Starting bot")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(start_services())