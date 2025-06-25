import aiohttp
import re
from bs4 import BeautifulSoup
from app.fetchers.base import BaseFetcher
from datetime import datetime

class GitHubTrendingFetcher(BaseFetcher):
    async def fetch(self):
        print(f"[{self.source_id}] Fetching GitHub trending page: {self.url}")
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url, headers=headers) as response:
                    if response.status != 200:
                        print(f"[{self.source_id}] Failed to fetch: {response.status}")
                        return []
                    html = await response.text()

            soup = BeautifulSoup(html, "html.parser")
            repos = soup.select("article.Box-row")

            result = []
            for repo in repos:
                repo_name = repo.h2.a.text.strip().replace("\n", "")

                stars = 0
                stars_element = repo.select_one(".mr-3 svg[aria-label='star']")
                if stars_element and stars_element.parent:
                    stars_text = stars_element.parent.text.strip()
                    match = re.search(r'([\d,]+)', stars_text)
                    if match:
                        stars = int(match.group(1).replace(',', ''))

                description = ""
                if repo.p:
                    description = repo.p.text.strip()

                language = ""
                lang_element = repo.select_one("[itemprop='programmingLanguage']")
                if lang_element:
                    language = lang_element.text.strip()

                news_item = {
                    "title": repo_name,
                    "link": "https://github.com" + repo.h2.a["href"],
                    "summary": description,
                    "published": datetime.now().isoformat(),
                    "source": self.source_id,
                    "lang": self.lang,
                    "stars": stars,
                    "language": language
                }
                result.append(news_item)

            return result

        except Exception as e:
            print(f"[{self.source_id}] Error fetching GitHub trending: {e}")
            return []