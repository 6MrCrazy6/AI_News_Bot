import os
import json
import logging
import re
import asyncio
from typing import Dict, List, Optional
import httpx
from bs4 import BeautifulSoup
from langdetect import detect_langs
from dotenv import load_dotenv

# Load environment variables
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
env_path = os.path.join(project_root, "keys", "keys.env")
load_dotenv(dotenv_path=env_path)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free")
ENABLE_FILTERING = os.getenv("ENABLE_FILTERING", "1") == "1"

# Configure logging
logger = logging.getLogger(__name__)

# PROMPTS
SUMMARY_PROMPT = """
Вы — «ИИ-редактор новостей», профессиональный технологический журналист.
Ваша задача — превратить сырую новость об ИИ в качественную заметку на русском языке.

Правила:
1. Язык — только русский. Имена компаний, продуктов и моделей (например, GPT-4, OpenAI) оставляйте в оригинале.
2. Длина: 
   - Если impact >= 4: развернуто (100-120 слов).
   - Если impact <= 3: кратко (40-60 слов).
3. Тон: Профессиональный, объективный, без лишнего хайпа.
4. Выходной формат: ТОЛЬКО чистый JSON.

JSON структура:
{
  "title": "Краткий и цепляющий заголовок на русском",
  "summary": "Основной текст новости на русском",
  "why": "Почему это важно для индустрии (до 25 слов)",
  "impact": 1-5
}
"""

TRANSLATION_PROMPT = """
Вы — профессиональный переводчик технических текстов. 
Переведите следующий текст на русский язык. 
Сохраняйте технические термины и названия брендов (OpenAI, LLM, GPT и т.д.) в оригинале.
Текст должен звучать естественно, как будто написан русскоязычным автором.
Не добавляйте никаких комментариев от себя, только перевод.

Текст для перевода:
"""

FILTER_PROMPT = """
Определите, относится ли эта новость к ИИ, стартапам или IT-технологиям.
Ответьте только "relevant" или "not_relevant".
"""

async def call_openrouter(prompt: str, content: str, json_mode: bool = False, retries: int = 3) -> Optional[str]:
    """Helper to call OpenRouter API with exponential backoff."""
    if not OPENROUTER_API_KEY:
        logger.error("OPENROUTER_API_KEY not found")
        return None

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/6MrCrazy6/AI_News_Bot",
        "X-Title": "AI News Bot"
    }

    data = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": content}
        ],
        "temperature": 0.3 if json_mode else 0.5
    }

    if json_mode:
        data["response_format"] = {"type": "json_object"}

    for attempt in range(retries):
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(url, json=data, headers=headers)
                
                if response.status_code == 429: # Rate limit
                    wait_time = (attempt + 1) * 5
                    logger.warning(f"Rate limited. Waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)
                    continue
                    
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"]["content"]
        except Exception as e:
            logger.error(f"OpenRouter API error (attempt {attempt+1}/{retries}): {e}")
            if attempt < retries - 1:
                await asyncio.sleep((attempt + 1) * 2)
    return None

def clean_text(text: str) -> str:
    """Clean HTML and limit length."""
    if not text: return ""
    soup = BeautifulSoup(text, "html.parser")
    clean = soup.get_text()
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean[:4000]

def detect_language(text: str) -> str:
    """Detect language."""
    if not text or len(text.strip()) < 10: return "unknown"
    try:
        langs = detect_langs(text)
        if langs and langs[0].prob >= 0.9:
            return langs[0].lang
    except:
        pass
    return "unknown"

async def ensure_russian_text(text: str) -> str:
    """Translate text to Russian using LLM."""
    if not text: return ""
    if detect_language(text) == "ru":
        return text

    logger.info(f"Translating text via LLM: {text[:50]}...")
    translated = await call_openrouter(TRANSLATION_PROMPT, text)
    return translated.strip() if translated else text

async def filter_relevant_news(news_item: Dict) -> bool:
    """Filter news relevance."""
    if not ENABLE_FILTERING: return True
    text = f"Title: {news_item.get('title')}\nContent: {news_item.get('summary', '')}"
    result = await call_openrouter(FILTER_PROMPT, text)
    return "relevant" in result.lower() if result else True

async def process_single_item(item: Dict) -> Optional[Dict]:
    """Process a single news item (for parallel execution)."""
    try:
        # Translate title if needed
        item["title"] = await ensure_russian_text(item.get("title", ""))
        
        # Generate summary
        content = f"Title: {item['title']}\nRaw Content: {item.get('summary', '')}"
        response = await call_openrouter(SUMMARY_PROMPT, content, json_mode=True)
        
        if response:
            try:
                data = json.loads(response)
                item.update({
                    "title": data.get("title", item["title"]),
                    "summary": data.get("summary", ""),
                    "why": data.get("why", ""),
                    "impact": data.get("impact", 1),
                    "score": item.get("score", 0) + data.get("impact", 1) * 2,
                    "summary_lang": "ru"
                })
                return item
            except:
                logger.error("Failed to parse LLM JSON response")
        
        # Fallback if LLM fails
        item["summary"] = item.get("summary", item["title"])
        item["impact"] = 1
        return item
    except Exception as e:
        logger.error(f"Error processing single item: {e}")
        return None

async def process_news_batch(news_items: List[Dict]) -> List[Dict]:
    """Process a batch of news items in parallel."""
    if not news_items: return []
    
    logger.info(f"Processing {len(news_items)} items in parallel...")
    tasks = [process_single_item(item) for item in news_items]
    results = await asyncio.gather(*tasks)
    
    # Filter out None results
    return [r for r in results if r is not None]
