import aiohttp
import logging
from app.fetchers.base import BaseFetcher

logger = logging.getLogger(__name__)

class JSONFeedFetcher(BaseFetcher):
    """
    Universal fetcher for JSON Feed format (https://jsonfeed.org/)
    """
    async def fetch(self):
        logger.info(f"[{self.source_id}] Fetching from JSON Feed: {self.url}")
        headers = {
            "User-Agent": "AI-News-Bot/1.0",
            "Accept": "application/json"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url, headers=headers, timeout=30) as response:
                    if response.status != 200:
                        logger.error(f"[{self.source_id}] Failed to fetch: HTTP {response.status}")
                        return []

                    try:
                        data = await response.json()
                    except Exception as e:
                        logger.error(f"[{self.source_id}] Failed to parse JSON: {e}")
                        return []

            # JSON Feed structure: { "items": [ { "title": "...", "url": "...", ... } ] }
            items = data.get("items", [])
            
            return [
                {
                    "title": item.get("title", ""),
                    "link": item.get("url", item.get("id", "")),
                    "summary": item.get("summary", item.get("content_text", "")),
                    "published": item.get("date_published", ""),
                    "source": self.source_id,
                    "lang": self.lang
                }
                for item in items if item.get("title") or item.get("url")
            ]
        except Exception as e:
            logger.error(f"[{self.source_id}] Error fetching JSON Feed: {e}")
            return []
