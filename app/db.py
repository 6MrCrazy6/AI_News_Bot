from dotenv import load_dotenv
import sqlite3
import os
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

load_dotenv(dotenv_path=os.path.join("keys", "keys.env"))

DB_PATH = os.getenv("DB_URL", "database/news.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    name TEXT,
    weight INTEGER DEFAULT 1,
    active BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS news_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT UNIQUE,
    title TEXT,
    source_id TEXT REFERENCES sources(id),
    published TIMESTAMP,
    score REAL,
    impact INTEGER,
    summary TEXT,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sent BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS news_reactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    news_id INTEGER REFERENCES news_items(id),
    message_id INTEGER,
    reaction_type TEXT CHECK (reaction_type IN ('like', 'dislike')),
    user_id INTEGER,
    username TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(news_id, user_id)
);
"""


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)

        cursor = conn.execute("PRAGMA table_info(news_items)")
        columns = [col[1] for col in cursor.fetchall()]

        if "summary_lang" not in columns:
            try:
                logger.info("Adding summary_lang column to news_items table")
                conn.execute("ALTER TABLE news_items ADD COLUMN summary_lang TEXT")
                conn.commit()
                logger.info("summary_lang column added successfully")
            except Exception as e:
                logger.error(f"Error adding summary_lang column: {e}")

        if "message_id" not in columns:
            try:
                logger.info("Adding message_id column to news_items table")
                conn.execute("ALTER TABLE news_items ADD COLUMN message_id INTEGER NULL")
                conn.commit()
                logger.info("message_id column added successfully")
            except Exception as e:
                logger.error(f"Error adding message_id column: {e}")


def get_connection():
    return sqlite3.connect(DB_PATH)


def add_source(source_id, name, weight=1, active=True):
    with get_connection() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO sources (id, name, weight, active) VALUES (?, ?, ?, ?)",
            (source_id, name, weight, int(active))
        )
        conn.commit()


def get_active_sources():
    with get_connection() as conn:
        cursor = conn.execute("SELECT id, name FROM sources WHERE active = 1")
        return cursor.fetchall()


def is_source_active(source_id):
    """Проверяет, активен ли источник в базе данных"""
    try:
        with get_connection() as conn:
            cursor = conn.execute("SELECT active FROM sources WHERE id = ?", (source_id,))
            result = cursor.fetchone()
            return bool(result[0]) if result else False
    except Exception as e:
        logger.error(f"Error checking source status: {e}")
        return False  # По умолчанию считаем неактивным, если произошла ошибка


def is_duplicate_url(url, days=3):  # Only consider duplicates if they're within the last 3 days
    """Check if URL exists and was processed recently."""
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT 1 FROM news_items WHERE url = ? AND processed_at > datetime('now', '-' || ? || ' days')",
            (url, days)
        )
        return cursor.fetchone() is not None


def add_news_item(url, title, source_id, published, score, impact, summary, summary_lang=None):
    """Добавляет новость в базу данных, с учетом возможного отсутствия колонки summary_lang"""
    if is_duplicate_url(url):
        return False

    with get_connection() as conn:
        # Проверяем наличие колонки summary_lang
        cursor = conn.execute("PRAGMA table_info(news_items)")
        columns = [col[1] for col in cursor.fetchall()]

        if "summary_lang" in columns:
            # Если колонка существует, используем полный запрос
            conn.execute(
                """
                INSERT INTO news_items (url, title, source_id, published, score, impact, summary, summary_lang)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (url, title, source_id, published, score, impact, summary, summary_lang)
            )
        else:
            # Если колонки нет, используем запрос без нее
            conn.execute(
                """
                INSERT INTO news_items (url, title, source_id, published, score, impact, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (url, title, source_id, published, score, impact, summary)
            )
        conn.commit()
    return True


def get_unsent_news():
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM news_items WHERE sent = 0 ORDER BY score DESC")
        return cursor.fetchall()


def mark_as_sent(news_id, message_id=None):
    """Помечает новость как отправленную, с безопасной проверкой на наличие колонки message_id"""
    with get_connection() as conn:
        try:
            # Проверяем, есть ли колонка message_id
            cursor = conn.execute("PRAGMA table_info(news_items)")
            columns = [col[1] for col in cursor.fetchall()]

            if message_id and "message_id" in columns:
                conn.execute("UPDATE news_items SET sent = 1, message_id = ? WHERE id = ?", (message_id, news_id))
            else:
                conn.execute("UPDATE news_items SET sent = 1 WHERE id = ?", (news_id,))
            conn.commit()
        except Exception as e:
            logger.error(f"Error marking news item {news_id} as sent: {e}")
            # Пытаемся использовать самый простой запрос как запасной вариант
            try:
                conn.execute("UPDATE news_items SET sent = 1 WHERE id = ?", (news_id,))
                conn.commit()
            except Exception as backup_error:
                logger.error(f"Backup error marking news item {news_id} as sent: {backup_error}")


def get_source_weight(source_id: str) -> int:
    with get_connection() as conn:
        cursor = conn.execute("SELECT weight FROM sources WHERE id = ?", (source_id,))
        result = cursor.fetchone()
        if result:
            return int(result[0])
        return 1


# Функции для работы с реакциями
def add_reaction(news_id, message_id, reaction_type, user_id, username):
    """
    Добавляет или обновляет реакцию пользователя на новость.
    Обрабатывает возможные ошибки БД.
    """
    if reaction_type not in ('like', 'dislike'):
        logger.warning(f"Invalid reaction type: {reaction_type}")
        return False

    with get_connection() as conn:
        try:
            # Проверяем, есть ли уже реакция от этого пользователя
            cursor = conn.execute(
                "SELECT reaction_type FROM news_reactions WHERE news_id = ? AND user_id = ?",
                (news_id, user_id)
            )
            existing = cursor.fetchone()

            if existing:
                # Если такая же реакция - удаляем (toggle)
                if existing[0] == reaction_type:
                    conn.execute(
                        "DELETE FROM news_reactions WHERE news_id = ? AND user_id = ?",
                        (news_id, user_id)
                    )
                    logger.debug(f"User {user_id} removed {reaction_type} from news {news_id}")
                else:
                    # Если другая реакция - обновляем
                    conn.execute(
                        "UPDATE news_reactions SET reaction_type = ? WHERE news_id = ? AND user_id = ?",
                        (reaction_type, news_id, user_id)
                    )
                    logger.debug(f"User {user_id} changed reaction to {reaction_type} for news {news_id}")
            else:
                # Если реакции не было - добавляем новую
                conn.execute(
                    """
                    INSERT INTO news_reactions 
                    (news_id, message_id, reaction_type, user_id, username) 
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (news_id, message_id, reaction_type, user_id, username)
                )
                logger.debug(f"User {user_id} added {reaction_type} to news {news_id}")

            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding reaction: {e}")
            return False


def get_news_reactions(news_id):
    """
    Возвращает количество лайков и дизлайков для конкретной новости.
    Возвращает пустой список в случае ошибки, чтобы не блокировать дальнейшее выполнение.
    """
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT reaction_type, COUNT(*) as count
                FROM news_reactions
                WHERE news_id = ?
                GROUP BY reaction_type
                """,
                (news_id,)
            )
            return cursor.fetchall()
    except Exception as e:
        logger.error(f"Error getting news reactions for news_id {news_id}: {e}")
        return []  # Возвращаем пустой список, чтобы избежать ошибок


def get_news_by_message_id(message_id):
    """
    Находит новость по ID сообщения Telegram.
    Полезно для обратной связи с кнопками.
    """
    try:
        with get_connection() as conn:
            # Проверяем, существует ли колонка message_id
            cursor = conn.execute("PRAGMA table_info(news_items)")
            columns = [col[1] for col in cursor.fetchall()]

            if "message_id" in columns:
                cursor = conn.execute(
                    """
                    SELECT id FROM news_items 
                    WHERE message_id = ?
                    """,
                    (message_id,)
                )
                result = cursor.fetchone()
                return result[0] if result else None
            else:
                return None
    except Exception as e:
        logger.error(f"Error finding news by message_id {message_id}: {e}")
        return None


def get_reactions_stats(period_days=7):
    """Возвращает статистику реакций за указанный период"""
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
                AND (
                    EXISTS (SELECT 1 FROM news_reactions WHERE news_id = n.id AND reaction_type = 'like')
                    OR EXISTS (SELECT 1 FROM news_reactions WHERE news_id = n.id AND reaction_type = 'dislike')
                )
            ORDER BY
                likes DESC, dislikes ASC
            LIMIT 20
            """,
            (period_str,)
        )
        return cursor.fetchall()


def get_source_reaction_stats(period_days=30):
    """Возвращает статистику реакций по источникам за указанный период"""
    period_date = datetime.now() - timedelta(days=period_days)
    period_str = period_date.strftime("%Y-%m-%d %H:%M:%S")

    with get_connection() as conn:
        cursor = conn.execute(
            """
            SELECT 
                n.source_id,
                COUNT(DISTINCT n.id) as news_count,
                COUNT(DISTINCT CASE WHEN r.reaction_type = 'like' THEN r.id END) as likes,
                COUNT(DISTINCT CASE WHEN r.reaction_type = 'dislike' THEN r.id END) as dislikes
            FROM 
                news_items n
            LEFT JOIN
                news_reactions r ON n.id = r.news_id
            WHERE
                n.processed_at >= ?
            GROUP BY
                n.source_id
            ORDER BY
                likes DESC
            """,
            (period_str,)
        )
        return cursor.fetchall()


def cleanup_old_news(days=30):
    """Deletes news older than the specified number of days"""
    try:
        with get_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM news_items WHERE processed_at < datetime('now', '-' || ? || ' days')",
                (days,)
            )
            deleted_count = cursor.rowcount
            conn.commit()
            return deleted_count
    except Exception as e:
        logger.error(f"Error cleaning up old news: {e}")
        return 0