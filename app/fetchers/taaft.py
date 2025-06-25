import aiohttp
from app.fetchers.base import BaseFetcher

class TAAFTFetcher(BaseFetcher):
    async def fetch(self):
        print(f"[{self.source_id}] Fetching from TAAFT API: {self.url}")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
            "Accept": "application/json",
            "Referer": "https://theresanaiforthat.com/",
            "Origin": "https://theresanaiforthat.com"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url, headers=headers) as response:
                    if response.status != 200:
                        print(f"[{self.source_id}] Failed to fetch: HTTP {response.status}")
                        return []

                    try:
                        data = await response.json()
                    except Exception as e:
                        print(f"[{self.source_id}] Failed to parse JSON: {e}")
                        return []

            return [
                {
                    "title": entry.get("name", ""),
                    "link": entry.get("url", ""),
                    "summary": entry.get("description", ""),
                    "published": entry.get("published_at", ""),
                    "source": self.source_id,
                    "lang": self.lang
                }
                for entry in data
            ]
        except Exception as e:
            print(f"[{self.source_id}] Error fetching data: {e}")
            return []