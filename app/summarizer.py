import difflib
from typing import List, Dict
from db import add_news_item, is_duplicate_url
from llm_processor import process_news_batch, ensure_russian_text, detect_language
import logging
from common import clean_html

logger = logging.getLogger(__name__)


def is_similar(title1: str, title2: str, threshold: float = 0.85) -> bool:
    """Check if two titles are similar enough to be considered duplicates"""
    if not title1 or not title2:
        return False
    return difflib.SequenceMatcher(None, title1.lower(), title2.lower()).ratio() >= threshold


def remove_title_duplicates(news_list: List[Dict]) -> List[Dict]:
    """Remove items with similar titles from the news list"""
    unique = []
    seen = []

    for news in news_list:
        title = news.get("title", "")
        if not title:
            continue

        if any(is_similar(title, s) for s in seen):
            continue
        seen.append(title)
        unique.append(news)

    return unique


async def process_news_async(news_items: List[Dict]) -> List[Dict]:
    """
    Process news items asynchronously:
    1. Clean HTML in all fields
    2. Translate titles to Russian
    3. Remove duplicates by title
    4. Filter out items already in DB
    5. Process through LLM pipeline
    6. Store in database
    """
    if not news_items:
        logger.warning("Received empty news_items list")
        return []

    logger.info(f"Starting to process {len(news_items)} items")

    # Предварительная очистка HTML во всех полях
    for item in news_items:
        if "title" in item:
            item["title"] = clean_html(item["title"])
        if "summary" in item:
            item["summary"] = clean_html(item["summary"])
        if "content" in item:
            item["content"] = clean_html(item["content"])

    # Принудительный перевод заголовков на русский язык
    for item in news_items:
        if "title" in item and item["title"]:
            title_lang = detect_language(item["title"])
            if title_lang != "ru" and len(item["title"]) > 10:
                logger.info(f"Translating title to Russian: {item['title'][:50]}...")
                try:
                    item["title"] = await ensure_russian_text(item["title"])
                    logger.info(f"Translation result: {item['title'][:50]}...")
                except Exception as e:
                    logger.error(f"Error translating title: {e}")

    # Step 1: Remove title duplicates
    unique_items = remove_title_duplicates(news_items)
    logger.info(f"After title deduplication: {len(unique_items)} items")

    # Step 2: Filter out items already in DB
    filtered_items = []
    for item in unique_items:
        url = item.get("url") or item.get("link", "")
        if not url:
            logger.warning(f"Skipping item with no URL: {item.get('title', 'Unknown')}")
            continue

        if is_duplicate_url(url):
            logger.debug(f"Skipping duplicate URL: {url}")
            continue

        item["url"] = url
        filtered_items.append(item)

    logger.info(f"After URL deduplication: {len(filtered_items)} items")

    if not filtered_items:
        logger.info("No new items to process after filtering")
        return []

    # Step 3: Process through LLM pipeline
    try:
        processed_items = await process_news_batch(filtered_items)
        logger.info(f"Successfully processed {len(processed_items)} items through LLM")
    except Exception as e:
        logger.error(f"Error in process_news_batch: {e}")
        # If LLM processing fails, use basic processing for the items
        processed_items = []
        for item in filtered_items:
            item.update({
                "summary": item.get("title", ""),
                "impact": 1,
                "summary_lang": "unknown"
            })
            processed_items.append(item)
        logger.info(f"Fallback: using {len(processed_items)} items with basic processing")

    # Step 4: Store in database
    result = []
    for item in processed_items:
        try:
            url = item.get("url", "")
            title = item.get("title", "")
            source_id = item.get("source_id", "unknown")
            published = item.get("published")
            score = item.get("score", 0)
            impact = item.get("impact", 1)
            summary = item.get("summary", "")
            summary_lang = item.get("summary_lang", "unknown")

            logger.debug(f"Adding to DB: {title} (impact: {impact})")

            success = add_news_item(
                url=url,
                title=title,
                source_id=source_id,
                published=published,
                score=score,
                impact=impact,
                summary=summary,
                summary_lang=summary_lang
            )

            if success:
                result.append(item)
                logger.debug(f"Successfully added {title} to database")
            else:
                logger.warning(f"Failed to add {title} to database")

        except Exception as e:
            logger.error(f"Error adding item to database: {e}, item: {item.get('title', 'Unknown')}")

    logger.info(f"Added {len(result)} new items to database")
    return result


async def process_news(news_items: List[Dict]) -> List[Dict]:
    """Main entry function for news processing"""
    return await process_news_async(news_items)