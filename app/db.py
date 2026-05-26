from dotenv import load_dotenv
import sqlite3
import os
from datetime import datetime, timedelta
import logging
from contextlib import contextmanager

logger = logging.getLogger(__name__)

# Load environment variables
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
env_path = os.path.join(project_root, "keys", "keys.env")
load_dotenv(dotenv_path=env_path)

DB_PATH = os.getenv("DB_URL", "app/database/news.db")

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
    summary_lang TEXT,
    message_id INTEGER NULL,
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

-- Optimization: Add indexes for faster lookups
CREATE INDEX IF NOT EXISTS idx_news_url ON news_items(url);
CREATE INDEX IF NOT EXISTS idx_news_sent ON news_items(sent);
CREATE INDEX IF NOT EXISTS idx_news_processed_at ON news_items(processed_at);
"""

@contextmanager
def get_connection():
    """Context manager for DB connections with optimized settings."""
    conn = sqlite3.connect(DB_PATH, timeout=20) # Increase timeout for concurrent access
    conn.row_factory = sqlite3.Row # Return rows as dict-like objects
    try:
        # Enable WAL mode for better concurrency
        conn.execute("PRAGMA journal_mode=WAL")
        yield conn
    finally:
        conn.close()

def init_db():
    """Initialize database and ensure all columns exist."""
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
        
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        
        # Check for missing columns (migration safety)
        cursor = conn.execute("PRAGMA table_info(news_items)")
        columns = [col[1] for col in cursor.fetchall()]
        
        if "summary_lang" not in columns:
            conn.execute("ALTER TABLE news_items ADD COLUMN summary_lang TEXT")
            conn.commit()
            
        if "message_id" not in columns:
            conn.execute("ALTER TABLE news_items ADD COLUMN message_id INTEGER NULL")
            conn.commit()

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
        return [dict(row) for row in cursor.fetchall()]

def is_source_active(source_id):
    with get_connection() as conn:
        cursor = conn.execute("SELECT active FROM sources WHERE id = ?", (source_id,))
        result = cursor.fetchone()
        return bool(result['active']) if result else False

def is_duplicate_url(url, days=3):
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT 1 FROM news_items WHERE url = ? AND processed_at > datetime('now', '-' || ? || ' days')",
            (url, days)
        )
        return cursor.fetchone() is not None

def add_news_item(url, title, source_id, published, score, impact, summary, summary_lang=None):
    if is_duplicate_url(url):
        return False
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO news_items (url, title, source_id, published, score, impact, summary, summary_lang)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (url, title, source_id, published, score, impact, summary, summary_lang)
        )
        conn.commit()
    return True

def get_unsent_news():
    with get_connection() as conn:
        cursor = conn.execute("SELECT * FROM news_items WHERE sent = 0 ORDER BY score DESC")
        return [dict(row) for row in cursor.fetchall()]

def mark_as_sent(news_id, message_id=None):
    with get_connection() as conn:
        conn.execute(
            "UPDATE news_items SET sent = 1, message_id = ? WHERE id = ?", 
            (message_id, news_id)
        )
        conn.commit()

def get_source_weight(source_id: str) -> int:
    with get_connection() as conn:
        cursor = conn.execute("SELECT weight FROM sources WHERE id = ?", (source_id,))
        result = cursor.fetchone()
        return int(result['weight']) if result else 1

def add_reaction(news_id, message_id, reaction_type, user_id, username):
    with get_connection() as conn:
        try:
            cursor = conn.execute(
                "SELECT reaction_type FROM news_reactions WHERE news_id = ? AND user_id = ?",
                (news_id, user_id)
            )
            existing = cursor.fetchone()

            if existing:
                if existing['reaction_type'] == reaction_type:
                    conn.execute("DELETE FROM news_reactions WHERE news_id = ? AND user_id = ?", (news_id, user_id))
                else:
                    conn.execute("UPDATE news_reactions SET reaction_type = ? WHERE news_id = ? AND user_id = ?", 
                                (reaction_type, news_id, user_id))
            else:
                conn.execute(
                    "INSERT INTO news_reactions (news_id, message_id, reaction_type, user_id, username) VALUES (?, ?, ?, ?, ?)",
                    (news_id, message_id, reaction_type, user_id, username)
                )
            conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error adding reaction: {e}")
            return False

def get_news_reactions(news_id):
    with get_connection() as conn:
        cursor = conn.execute(
            "SELECT reaction_type, COUNT(*) as count FROM news_reactions WHERE news_id = ? GROUP BY reaction_type",
            (news_id,)
        )
        return [dict(row) for row in cursor.fetchall()]

def get_news_by_message_id(message_id):
    with get_connection() as conn:
        cursor = conn.execute("SELECT id FROM news_items WHERE message_id = ?", (message_id,))
        result = cursor.fetchone()
        return result['id'] if result else None

def cleanup_old_news(days=30):
    with get_connection() as conn:
        cursor = conn.execute("DELETE FROM news_items WHERE processed_at < datetime('now', '-' || ? || ' days')", (days,))
        count = cursor.rowcount
        conn.commit()
        return count
