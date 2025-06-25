import aiohttp
import feedparser
from app.fetchers.base import BaseFetcher
from app.common import clean_html

class RSSFetcher(BaseFetcher):
    async def fetch(self):
        print(f"[{self.source_id}] Fetching RSS feed from {self.url}")
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url) as response:
                    content = await response.read()

            feed = feedparser.parse(content)
            return [
                {
                    "title": clean_html(entry.get("title", "")),
                    "link": entry.get("link", ""),
                    "summary": clean_html(entry.get("summary", "")),
                    "published": entry.get("published", ""),
                    "source": self.source_id,
                    "lang": self.lang
                }
                for entry in feed.entries
            ]
        except Exception as e:
            print(f"[{self.source_id}] Error fetching RSS: {e}")
            return []