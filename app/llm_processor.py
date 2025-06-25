import os
import json
import logging
import re
from typing import Dict, List
import httpx
from bs4 import BeautifulSoup
from langdetect import detect_langs
from dotenv import load_dotenv
from translate import Translator

# Load environment variables
load_dotenv(dotenv_path=os.path.join("keys", "keys.env"))

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
ENABLE_FILTERING = os.getenv("ENABLE_FILTERING", "1") == "1"  # Enabled by default

# Configure logging
logger = logging.getLogger(__name__)

# PROMPTS
SUMMARY_PROMPT = """
Вы — «ИИ-редактор новостей», русскоязычный технологический журналист-профессионал.  
Ваша задача — превратить сырую новость об искусственном интеллекте в структурированную, удобную для публикации заметку.

Правила для КАЖДОЙ новости:

1. Язык — только русский; имена продуктов, компаний и моделей оставляйте как в оригинале.  
2. Длина зависит от важности  
   * Если событие значительное (оценка impact ≥ 4) → развернутое описание 100–120 слов.  
   * Если событие обычное (impact ≤ 3) → короткое изложение 40–60 слов.  
3. Структура ответа — вернуть ТОЛЬКО корректный JSON UTF-8 без комментариев или Markdown.  
   ```json
   {
     "title": "краткий заголовок",
     "summary": "основной текст, 40–120 слов в зависимости от impact",
     "why": "Коментарий ИИ по поводу новости: почему это важно, ≤ 25 слов",
     "impact": 1–5,
     "link": " Topic Name (formatted link: https://example.com"
   }
"""

FILTER_PROMPT = """
Определите, относится ли эта новость к одной из следующих тем:
1. Искусственный интеллект (ИИ)
2. Стартапы и инновации
3. IT и технологии

Ответьте только "relevant" или "not_relevant".

Новость:
"""


def clean_text(text: str) -> str:
    """Remove HTML tags, emojis, and limit length."""
    if not text:
        return ""

    soup = BeautifulSoup(text, "html.parser")
    clean = soup.get_text()

    emoji_pattern = re.compile(
        "["
        "\U0001F600-\U0001F64F"  
        "\U0001F300-\U0001F5FF"  
        "\U0001F680-\U0001F6FF"  
        "\U0001F700-\U0001F77F" 
        "\U0001F780-\U0001F7FF"  
        "\U0001F800-\U0001F8FF"  
        "\U0001F900-\U0001F9FF"  
        "\U0001FA00-\U0001FA6F"  
        "\U0001FA70-\U0001FAFF" 
        "\U00002702-\U000027B0"  
        "\U000024C2-\U0001F251"
        "]+", flags=re.UNICODE
    )
    clean = emoji_pattern.sub(r'', clean)

    # Remove markdown artifacts
    clean = re.sub(r'#{1,6}\s+', '', clean)  # headers
    clean = re.sub(r'\*\*|\*|~~|__', '', clean)  # bold, italic, strikethrough

    # Limit length to 4000 characters
    if len(clean) > 4000:
        # Try to cut at a sentence boundary
        cutoff = clean[:4000].rfind('.')
        if cutoff > 3500:  # If we found a period in the reasonable range
            clean = clean[:cutoff + 1]
        else:
            clean = clean[:4000]

    return clean.strip()


def detect_language(text: str) -> str:
    """Detect the language of the text."""
    if not text or len(text.strip()) < 10:
        return "unknown"

    try:
        langs = detect_langs(text)
        if langs and langs[0].prob >= 0.99:
            return langs[0].lang
        return "unknown"
    except Exception as e:
        logger.warning(f"Language detection failed: {e}")
        return "unknown"


async def ensure_russian_text(text: str, preserve_names: bool = True) -> str:
    """
    Принудительно переводит текст на русский язык, используя библиотеку translate.
    """
    detected_lang = detect_language(text)
    logger.info(f"Определен язык текста: {detected_lang} для текста: {text[:50]}...")

    if detected_lang == "ru":
        logger.info("Текст уже на русском, пропускаем перевод")
        return text

    try:
        source_lang = 'en' if detected_lang == 'en' else 'auto'

        tech_terms = []
        if preserve_names:
            pattern = r'\b(GPT-[0-9]+|DALL-E[0-9]*|Midjourney|OpenAI|Google|Microsoft|DeepMind|Anthropic|Claude|Gemini|GitHub|Tesla|Apple|Amazon|Meta)\b'
            tech_terms = re.findall(pattern, text, re.IGNORECASE)

        translator = Translator(to_lang="ru", from_lang=source_lang)

        translated_text = translator.translate(text)
        logger.info(f"Результат перевода: {translated_text[:50]}...")

        if tech_terms:
            for term in tech_terms:
                try:
                    translated_term = translator.translate(term)
                    if translated_term in translated_text:
                        translated_text = translated_text.replace(translated_term, term)
                except:
                    pass

        result_lang = detect_language(translated_text)
        if result_lang != "ru":
            logger.warning(f"Перевод не дал русского текста: {result_lang}. Пробуем еще раз.")
            try:
                translator2 = Translator(to_lang="ru", from_lang="en")
                translated_text = translator2.translate(text)
                result_lang = detect_language(translated_text)
                if result_lang != "ru":
                    logger.error(f"Вторая попытка перевода не удалась: {result_lang}")
                    return f"[Требуется перевод] {text}"
            except Exception as e2:
                logger.error(f"Ошибка при второй попытке перевода: {e2}")
                return f"[Требуется перевод] {text}"

        return translated_text

    except Exception as e:
        logger.error(f"Ошибка при переводе текста: {e}")
        return f"[Требуется перевод] {text}"


async def filter_relevant_news(news_item: Dict) -> bool:
    """
    Filter news items to only keep those related to AI, startups, or IT.
    Returns True if the news item is relevant, False otherwise.
    """
    if not ENABLE_FILTERING or not GOOGLE_API_KEY:
        logger.warning("GOOGLE_API_KEY not found or filtering disabled, skipping relevance filtering")
        return True

    title = clean_text(news_item.get("title", ""))
    content = clean_text(news_item.get("content", "") or news_item.get("summary", ""))

    combined_text = f"Заголовок: {title}\n\nСодержание: {content}"

    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": GOOGLE_API_KEY
        }

        data = {
            "contents": [
                {
                    "parts": [
                        {"text": FILTER_PROMPT},
                        {"text": combined_text}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 10
            }
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(url, json=data, headers=headers)
            response.raise_for_status()

        result = response.json()
        generated_text = result["candidates"][0]["content"]["parts"][0]["text"].strip().lower()

        logger.debug(f"Filter result for '{title}': {generated_text}")

        return "relevant" in generated_text

    except Exception as e:
        logger.error(f"Error filtering news item '{title}': {e}")
        return True

async def process_with_gemini(payload: Dict) -> Dict:
    """Process text with Gemini Flash API with strict Russian language enforcement."""
    if not GOOGLE_API_KEY:
        logger.error("GOOGLE_API_KEY not found in environment")

        title = payload.get("title", "")
        summary = payload.get("title", "")
        return {
            "title": title,
            "summary": summary,
            "why": "",
            "impact": 1,
            "summary_lang": detect_language(summary)
        }

    title = clean_text(payload.get("title", ""))
    content = clean_text(payload.get("content", ""))

    source_lang = payload.get("lang", detect_language(content or title))

    prompt = SUMMARY_PROMPT
    formatted_content = f"Заголовок: {title}\n\nСодержание: {content}\n\nИсходный язык: {source_lang}\nЯзык описания: РУССКИЙ"

    try:
        url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash-latest:generateContent"
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": GOOGLE_API_KEY
        }

        data = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {"text": formatted_content}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "topP": 0.95,
                "topK": 40,
                "maxOutputTokens": 800
            }
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(url, json=data, headers=headers)
            response.raise_for_status()

        result = response.json()

        try:
            generated_text = result["candidates"][0]["content"]["parts"][0]["text"]

            json_str = generated_text.strip()
            json_match = re.search(r'({.*})', json_str, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)

            response_data = json.loads(json_str)

            if "summary" not in response_data or "impact" not in response_data:
                logger.warning(f"Invalid response from Gemini: {response_data}")
                return {
                    "title": title,
                    "summary": title,
                    "why": "",
                    "impact": 1,
                    "summary_lang": detect_language(title)
                }

            title = response_data.get("title", title)
            summary = response_data.get("summary", "")
            why = response_data.get("why", "")

            title_lang = detect_language(title)
            summary_lang = detect_language(summary)
            why_lang = detect_language(why)

            if title_lang != "ru" and len(title) > 10:
                logger.warning(f"Title не на русском языке ({title_lang})! Выполняем принудительный перевод.")
                title = await ensure_russian_text(title)
                title_lang = "ru"

            if summary_lang != "ru" and len(summary) > 10:
                logger.warning(f"Summary не на русском языке ({summary_lang})! Выполняем принудительный перевод.")
                summary = await ensure_russian_text(summary)
                summary_lang = "ru"

            if why_lang != "ru" and len(why) > 5:
                logger.warning(f"Why не на русском языке ({why_lang})! Выполняем принудительный перевод.")
                why = await ensure_russian_text(why)
                why_lang = "ru"

            impact = int(response_data.get("impact", 1))
            if impact < 1 or impact > 5:
                impact = max(1, min(5, impact))

            return {
                "title": title,
                "summary": summary,
                "why": why,
                "impact": impact,
                "summary_lang": summary_lang
            }

        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error(f"Failed to parse Gemini response: {e}, response: {result}")
            return {
                "title": title,
                "summary": title,
                "why": "",
                "impact": 1,
                "summary_lang": detect_language(title)
            }

    except httpx.RequestError as e:
        logger.error(f"Request to Gemini API failed: {e}")
        return {
            "title": title,
            "summary": title,
            "why": "",
            "impact": 1,
            "summary_lang": detect_language(title)
        }


async def process_with_gpt4o(payload: Dict) -> Dict:
    """Process high-impact news with GPT-4o for better quality."""
    if not OPENAI_API_KEY:
        logger.error("OPENAI_API_KEY not found in environment")
        return payload

    initial_summary = payload.get("summary", "")
    why = payload.get("why", "")
    title = payload.get("title", "")

    current_lang = detect_language(initial_summary)
    title_lang = detect_language(title)
    logger.info(
        f"Current summary language: {current_lang}, title language: {title_lang}, ensuring output is in Russian")

    prompt = f"""
Вы - эксперт-редактор новостей об искусственном интеллекте, который улучшает важные новости для русскоязычной аудитории.
Оригинальный заголовок: {title}
Начальное краткое содержание: {initial_summary}
Начальное 'почему это важно': {why}

Задача: 
1) Перевести и улучшить заголовок, сделать его ясным и привлекательным для русскоязычных читателей
2) Улучшить краткое содержание, сделать его более лаконичным и мощным (≤ 50 слов)
3) Добавить призыв к действию, например фразу "[Читать далее]" в конце
4) ВАЖНО: Весь текст (заголовок, содержание, пояснения) ОБЯЗАТЕЛЬНО должен быть на РУССКОМ языке, независимо от языка оригинала
5) Сохранить высокую значимость новости (это срочная важная новость)

Верните ТОЛЬКО корректный JSON:
{{"title":"…","summary":"…","why":"…","impact":int}}
    """

    try:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {OPENAI_API_KEY}"
        }

        data = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system",
                 "content": "Вы - эксперт-редактор новостей об ИИ для русскоязычной аудитории. Все ответы ТОЛЬКО на русском языке."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 800
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(url, json=data, headers=headers)
            response.raise_for_status()

        result = response.json()

        try:
            generated_text = result["choices"][0]["message"]["content"]

            json_str = generated_text.strip()
            json_match = re.search(r'({.*})', json_str, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)

            response_data = json.loads(json_str)

            if "summary" not in response_data:
                logger.warning(f"Invalid response from GPT-4o: {response_data}")
                return payload

            title = response_data.get("title", "")
            summary = response_data.get("summary", "")
            why_text = response_data.get("why", "")

            title_lang = detect_language(title)
            summary_lang = detect_language(summary)
            why_lang = detect_language(why_text)

            if title_lang != "ru" and len(title) > 10:
                logger.warning(
                    f"GPT-4o title не на русском языке ({title_lang})! Выполняем принудительный перевод.")
                title = await ensure_russian_text(title)
                title_lang = "ru"

            if summary_lang != "ru" and len(summary) > 10:
                logger.warning(
                    f"GPT-4o summary не на русском языке ({summary_lang})! Выполняем принудительный перевод.")
                summary = await ensure_russian_text(summary)
                summary_lang = "ru"

            if why_lang != "ru" and len(why_text) > 5:
                logger.warning(f"GPT-4o why не на русском языке ({why_lang})! Выполняем принудительный перевод.")
                why_text = await ensure_russian_text(why_text)
                why_lang = "ru"

            impact = int(response_data.get("impact", 4))
            if impact < 4:
                impact = 4
            elif impact > 5:
                impact = 5

            return {
                "title": title,
                "summary": summary,
                "why": why_text,
                "impact": impact,
                "summary_lang": summary_lang
            }

        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error(f"Failed to parse GPT-4o response: {e}, response: {result}")
            return payload

    except httpx.RequestError as e:
        logger.error(f"Request to OpenAI API failed: {e}")
        return payload


async def process_news_batch(news_items: List[Dict]) -> List[Dict]:
    result = []
    filtered_items = []

    if not news_items:
        logger.warning("Received empty news_items list")
        return []

    max_items = 50
    news_to_process = news_items[:max_items]
    logger.info(f"Processing {len(news_to_process)} news items (limited to {max_items})")

    if GOOGLE_API_KEY and ENABLE_FILTERING:
        for item in news_to_process:
            is_relevant = await filter_relevant_news(item)
            if is_relevant:
                filtered_items.append(item)
            else:
                logger.info(f"Filtered out non-relevant news: {item.get('title', '')}")

        logger.info(f"After filtering: {len(filtered_items)} of {len(news_to_process)} items kept")
    else:
        filtered_items = news_to_process
        logger.info(f"Skipping filtering, all {len(news_to_process)} items kept")

    for item in filtered_items:
        if "title" in item and item["title"]:
            title_lang = detect_language(item["title"])
            if title_lang != "ru" and len(item["title"]) > 10:
                try:
                    item["title"] = await ensure_russian_text(item["title"])
                    logger.info(f"Заголовок переведен: {item['title'][:50]}...")
                except Exception as e:
                    logger.error(f"Ошибка при переводе заголовка: {e}")

    for item in filtered_items:
        title = item.get("title", "")
        content = item.get("summary", "")
        lang = item.get("lang", "")

        try:
            payload = {
                "title": title,
                "content": content,
                "lang": lang
            }

            try:
                if GOOGLE_API_KEY:
                    llm_result = await process_with_gemini(payload)
                else:
                    llm_result = {
                        "title": title,
                        "summary": content or title,
                        "why": "",
                        "impact": 1,
                        "summary_lang": detect_language(content or title)
                    }

                    title_lang = detect_language(llm_result["title"])
                    summary_lang = detect_language(llm_result["summary"])

                    if title_lang != "ru" and len(llm_result["title"]) > 10:
                        llm_result["title"] = await ensure_russian_text(llm_result["title"])

                    if summary_lang != "ru" and len(llm_result["summary"]) > 10:
                        llm_result["summary"] = await ensure_russian_text(llm_result["summary"])
                        llm_result["summary_lang"] = "ru"
            except Exception as gemini_error:
                logger.error(f"Error in processing for '{title}': {gemini_error}")
                # Fall back to basic result
                llm_result = {
                    "title": title,
                    "summary": content or title,
                    "why": "",
                    "impact": 1,
                    "summary_lang": "unknown"
                }

                try:
                    title_lang = detect_language(llm_result["title"])
                    if title_lang != "ru" and len(llm_result["title"]) > 10:
                        llm_result["title"] = await ensure_russian_text(llm_result["title"])
                except:
                    pass

            base_score = item.get("score", 0)
            llm_impact = llm_result.get("impact", 1)

            calculated_impact = max(llm_impact, round(base_score / 10))
            final_impact = max(1, min(5, calculated_impact))

            item.update({
                "title": llm_result.get("title", title),
                "summary": llm_result.get("summary", title),
                "why": llm_result.get("why", ""),
                "impact": final_impact,
                "llm_model": "gemini-flash" if GOOGLE_API_KEY else "basic-translation",
                "summary_lang": llm_result.get("summary_lang", "unknown")
            })

            result.append(item)

        except Exception as e:
            logger.error(f"Error processing item '{title}': {e}")
            item.update({
                "title": title,
                "summary": title,
                "impact": 1,
                "llm_model": "error",
                "summary_lang": "unknown"
            })
            result.append(item)

    high_impact_processed = 0
    if OPENAI_API_KEY:
        max_high_impact = 5
        for item in result:
            if item.get("impact", 0) >= 4 and high_impact_processed < max_high_impact:
                try:
                    enhanced = await process_with_gpt4o(item)

                    item.update({
                        "title": enhanced.get("title", item.get("title", "")),
                        "summary": enhanced.get("summary", item.get("summary", "")),
                        "why": enhanced.get("why", item.get("why", "")),
                        "impact": enhanced.get("impact", item.get("impact", 4)),
                        "llm_model": "gpt-4o-mini",
                        "summary_lang": enhanced.get("summary_lang", item.get("summary_lang", "unknown"))
                    })
                    high_impact_processed += 1

                except Exception as e:
                    logger.error(f"Error processing high-impact item with GPT-4o: {e}")

    logger.info(f"Processed {len(result)} items, including {high_impact_processed} high-impact items")
    return result