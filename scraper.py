import os
import json
import time
import re
import sys
from copy import deepcopy
from pathlib import Path
from urllib.parse import urljoin
from google import genai
from google.genai import types
from google.genai.errors import ClientError
import trafilatura

from scrape_common import (
    build_session,
    decode_bytes,
    decode_response,
    headers_for,
    is_useful_content,
    repair_mojibake,
)

# --- Configuration ---
API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL_ID = os.environ.get("GEMINI_MODEL_ID", "gemini-flash-latest")
ROOT_DIR = Path(__file__).resolve().parent
CACHE_DIR = ROOT_DIR / "html_cache"
DATA_FILE = ROOT_DIR / "data.json"
SESSION = build_session()
_client = None

URLS = {
    "SMBC": "https://www.smbc-card.com/mem/wp/vpoint_up_program/index.jsp",
    "MUFG": "https://www.cr.mufg.jp/mufgcard/point/global/save/convenience_store/index.html"
}

OFFICIAL_LINKS = {
    "SMBC": "https://www.smbc-card.com/mem/wp/vpoint_up_program/index.jsp",
    "MUFG": "https://www.cr.mufg.jp/mufgcard/point/global/save/convenience_store/index.html"
}

BASE_DOMAINS = {
    "SMBC": "https://www.smbc-card.com",
    "MUFG": "https://www.cr.mufg.jp"
}

REFERRAL_URLS = {
    "SMBC": os.environ.get("SMBC_REFERRAL_URL"),
    "MUFG": os.environ.get("MUFG_REFERRAL_URL")
}

def get_client():
    global _client
    if _client:
        return _client
    if not API_KEY:
        print("FATAL ERROR: 'GEMINI_API_KEY' environment variable is missing.", flush=True)
        sys.exit(1)

    # タイムアウト180秒
    _client = genai.Client(
        api_key=API_KEY,
        http_options=types.HttpOptions(timeout=180000)
    )
    return _client

def load_previous_output():
    if not DATA_FILE.exists():
        return {}
    try:
        with DATA_FILE.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"WARNING: Could not load previous data.json: {e}", flush=True)
        return {}

def fallback_items(card_name, reason):
    previous = load_previous_output()
    stores = [
        deepcopy(item)
        for item in previous.get("stores", [])
        if item.get("card_type") == card_name
    ]
    if stores:
        print(f"WARNING: Using previous {card_name} data ({len(stores)} items). Reason: {reason}", flush=True)
    else:
        print(f"ERROR: No previous {card_name} data available. Reason: {reason}", flush=True)
    return stores

def read_cached_html(card_name):
    cache_path = CACHE_DIR / f"{card_name}.html"
    if not cache_path.exists():
        print(f"ERROR: No local cache found at {cache_path}.", flush=True)
        return ""
    try:
        content = decode_bytes(cache_path.read_bytes())
        content = repair_mojibake(content)
        print(f"DEBUG: Local cache loaded ({len(content)} chars)", flush=True)
        return content
    except Exception as e:
        print(f"ERROR: Failed to load local cache: {e}", flush=True)
        return ""

def get_source_html(card_name, target_url, cache_only=False):
    if not cache_only:
        try:
            resp = SESSION.get(target_url, headers=headers_for(card_name), timeout=60)
            print(f"DEBUG: Direct fetch status={resp.status_code} for {card_name}", flush=True)
            resp.raise_for_status()
            raw_html = decode_response(resp)
            cleaned = clean_html_aggressive(raw_html, card_name)
            if is_useful_content(card_name, cleaned):
                print(f"DEBUG: Direct fetch validated ({len(cleaned)} chars)", flush=True)
                return raw_html, "direct"
            print("WARNING: Direct fetch did not contain expected official content. Checking cache...", flush=True)
        except Exception as e:
            print(f"WARNING: Direct fetch failed ({e}). Checking cache...", flush=True)
    else:
        print(f"DEBUG: Cache-only source check for {card_name}", flush=True)

    cached = read_cached_html(card_name)
    if not cached:
        return "", "missing"

    cleaned_cache = clean_html_aggressive(cached, card_name)
    if is_useful_content(card_name, cleaned_cache):
        print(f"DEBUG: Local cache validated ({len(cleaned_cache)} chars)", flush=True)
        return cached, "cache"

    return "", "invalid"

def check_sources(cache_only=False):
    ok = True
    for card_name, url in URLS.items():
        raw_html, source = get_source_html(card_name, url, cache_only=cache_only)
        if not raw_html:
            print(f"CHECK FAILED: {card_name} source unavailable ({source})", flush=True)
            ok = False
            continue
        content = clean_html_aggressive(raw_html, card_name)
        valid = is_useful_content(card_name, content)
        print(f"CHECK {card_name}: source={source}, chars={len(content)}, valid={valid}", flush=True)
        ok = ok and valid
    return 0 if ok else 1

def clean_json_text(text):
    if not text: return "[]"
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match: return match.group()
    return text.strip()

def clean_html_aggressive(html_text, card_name=""):
    """
    trafilatura を使ってHTMLからメインコンテンツを抽出
    MUFGの場合はBeautifulSoupで#anc01を抽出して直接返す
    """
    if not html_text:
        return ""
    
    # MUFGのみ、BeautifulSoupで#anc01を抽出して直接返す
    if card_name == "MUFG":
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html_text, 'html.parser')
            target = soup.select_one('#anc01')
            if target:
                section_text = target.get_text(separator=' ', strip=True)
                print(f"DEBUG: MUFG #anc01 extracted via BeautifulSoup ({len(section_text)} chars)", flush=True)
                return section_text[:95000]
        except Exception as e:
            print(f"WARNING: MUFG CSS selector extraction failed: {e}", flush=True)
    
    # trafilatura でメインコンテンツを抽出（テキスト形式）
    extracted = trafilatura.extract(
        html_text,
        output_format="txt",
        include_tables=True,
        include_links=True,
        no_fallback=False
    )
    
    if not extracted:
        # フォールバック: 元の正規表現ベースのクリーニング
        print("WARNING: trafilatura extraction failed, using regex fallback", flush=True)
        blocks_to_kill = r'<(header|footer|nav|noscript|script|style|iframe|svg|aside)[^>]*>.*?</\1>'
        html_text = re.sub(blocks_to_kill, '', html_text, flags=re.DOTALL | re.IGNORECASE)
        html_text = re.sub(r'<((?!a\s)[a-z0-9]+)\s+[^>]*>', r'<\1>', html_text, flags=re.IGNORECASE)
        html_text = re.sub(r'\n+', '\n', html_text)
        html_text = re.sub(r' +', ' ', html_text)
        return html_text[:95000].strip()
    
    # 文字数制限（Gemini API の制限に合わせる）
    return extracted[:50000].strip()

def generate_catchphrase(card_name, referral_text):
    if not referral_text or len(referral_text) < 50:
        return None
    print(f">>> Analyzing Referral Content for {card_name}...", flush=True)
    prompt = f"""
        あなたは合理的な金融アナリストです。提供された「リファラルサイトのテキスト」のみを解析してください。
        【タスク】
        このリンク経由でカードを発行した際の「ポイント還元額」や「限定特典」を1つ特定し、短いキャッチコピーを生成せよ。
        【絶対ルール】
        1. 提供されたテキストに記載のない数値を捏造することは厳禁。
        2. あなた自身の知識は一切使わず、目の前のテキストのみを根拠とせよ。
        【出力形式】
        JSON: {{ "catch": "事実に基づく文言" }}
        
        解析対象テキスト:
        {referral_text[:20000]}
    """
    try:
        response = get_client().models.generate_content(
            model=MODEL_ID, 
            contents=prompt,
            config={"response_mime_type": "application/json", "temperature": 0.0}
        )
        return json.loads(response.text).get("catch")
    except:
        return None

def fetch_and_extract(card_name, target_url):
    print(f"\n>>> Processing Official: {card_name}", flush=True)
    raw_html, source = get_source_html(card_name, target_url)
    if not raw_html:
        return fallback_items(card_name, f"source html unavailable ({source})")

    content = clean_html_aggressive(raw_html, card_name)

    if len(content) < 100:
        print("FATAL: Content is empty!", flush=True)
        return fallback_items(card_name, "cleaned content is empty")
        
    with open(ROOT_DIR / f"debug_input_{card_name}.html", "w", encoding="utf-8") as f:
        f.write(content)
        
    prompt = f"""
        You are an expert data analyst for Japanese credit card rewards (Poi-katsu).
        Analyze text and extract store data properly.

        【CRITICAL RULES】
        1. **OUTPUT LANGUAGE**: All string values MUST be in **JAPANESE**.
        
        2. **GROUP NAME**: You MUST extract formal group name if applicable.
           - Example: "ガスト" -> group: "すかいらーくグループ"
           - Example: "セブン-イレブン" -> group: null

        3. **ALIASES (略称)**: You MUST generate a rich list of search keywords, including slang.
           - **KANJI TO HIRAGANA**: If store name contains Kanji, you MUST include Hiragana reading in aliases.
           - "吉野家" -> ["よしのや", "吉牛", "よしの家"]
           - "McDonald's" -> ["マクド", "マック", "Mac", "マクドナルド"]
           - "Seicomart" -> ["セコマ", "セイコーマート", "せいこーまーと"]
           - "Seven-Eleven" -> ["セブン", "セブイレ", "セブンイレブン"]
        
        4. **MUFG SPECIAL CAUTION (Amex)**: 
           - **CRITICAL**: MUFG American Express rules are often NOT in text (provided only via images). 
           - For ALL MUFG stores, you MUST append this warning to `note`: "Amexは条件が異なる可能性があるため公式サイトを確認推奨".
           - Separate rules for Visa/Master/JCB vs Amex if text explicitly mentions it.

        5. **SPECIFIC STORE URLS**:
           - If text provides a specific URL for a store list (e.g., "サイゼリヤの対象店舗一覧はこちら", "ケンタッキー...はこちら"), EXTRACT that specific URL into `official_list_url`.
           - **Saizeriya (SMBC)**: Must link to specific store list URL if found.
           - **KFC (SMBC)**: Must link to specific store list URL if found.
           - If no specific list URL is found, set `official_list_url` to null.
           
        6. **COMMERCIAL FACILITIES (商業施設)**:
           - Check for footnotes or warnings about "commercial facilities" (商業施設).
           - If text mentions that stores inside commercial facilities/stations are excluded, you MUST explicitly include "商業施設内の店舗は対象外の場合あり" in `note`.
           - This is highly critical for SMBC related stores.

        【Output JSON Schema】
        Return a JSON ARRAY.
        {{
            "name": "Store Name (JAPANESE)",
            "group": "Group Name or null (JAPANESE)",
            "aliases": ["Array", "of", "search", "keywords (Include Hiragana)"],
            "conditions": {{
                "payment_method": "String (e.g., 'スマホタッチ決済のみ', '物理カードOK')",
                "mobile_order": "String (e.g., '対象外', '公式アプリのみ対象')",
                "delivery": "String (e.g., '対象外', '自社デリバリーは対象')",
                "note": "String (e.g., '商業施設内は対象外など')"
            }},
            "official_list_url": "Specific Store List URL or null"
        }}

        Target Text (Cleaned HTML):
        {content}
    """

    max_retries = 5
    response_text = ""

    for attempt in range(max_retries):
        try:
            print(f"DEBUG: Requesting Gemini... (Attempt {attempt+1})", flush=True)
            
            response = get_client().models.generate_content(
                model=MODEL_ID, 
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "temperature": 0.0,
                    "safety_settings": [
                        {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                        {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
                    ]
                }
            )
            response_text = response.text
            break 

        except ClientError as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                print(f"WARNING: Rate Limit (429). Sleeping 20s...", flush=True)
                time.sleep(20)
                continue
            else:
                print(f"CRITICAL API ERROR: {e}", flush=True)
                return fallback_items(card_name, "Gemini API client error")
        except Exception as e:
            print(f"WARNING: Network/Timeout Error ({e}).", flush=True)
            if attempt < max_retries - 1:
                print("Retrying in 20s...", flush=True)
                time.sleep(20)
                continue
            else:
                return fallback_items(card_name, "Gemini request failed after retries")
    
    try:
        with open(ROOT_DIR / f"debug_response_{card_name}.txt", "w", encoding="utf-8") as f:
            f.write(response_text if response_text else "EMPTY_RESPONSE")
    except:
        pass

    try:
        cleaned_json = clean_json_text(response_text)
        data = json.loads(cleaned_json)
        if not isinstance(data, list) or not data:
            return fallback_items(card_name, "Gemini response did not contain store items")
        print(f"SUCCESS: Extracted {len(data)} items for {card_name}", flush=True)
        return data
    except Exception as e:
        print(f"JSON PARSE ERROR: {e}", flush=True)
        with open(ROOT_DIR / f"debug_error_{card_name}.txt", "w", encoding="utf-8") as f:
            f.write(str(e) + "\n\n" + response_text)
        return fallback_items(card_name, "Gemini response was not valid JSON")

def main():
    print(f"--- INITIALIZING DEBUG SCRAPER (MODEL: {MODEL_ID}) ---", flush=True)

    final_stores_list = []
    previous_output = load_previous_output()
    meta_data = dict(previous_output.get("meta", {}))

    for i, (card, url) in enumerate(URLS.items()):
        items = fetch_and_extract(card, url)
        if items:
            base_domain = BASE_DOMAINS.get(card, "")
            for item in items:
                item["card_type"] = card
                item["source_url"] = OFFICIAL_LINKS[card]
                raw_url = item.get("official_list_url")
                if raw_url and not raw_url.startswith("http"):
                    item["official_list_url"] = urljoin(base_domain, raw_url)
                    print(f"DEBUG: Fixed URL -> {item['official_list_url']}", flush=True)
            final_stores_list.extend(items)

        ref_url = REFERRAL_URLS.get(card)

        if ref_url and ref_url != "#":
            meta_data[f"{card.lower()}_url"] = ref_url

            try:
                ref_resp = SESSION.get(ref_url, headers=headers_for(card), timeout=30)
                ref_resp.raise_for_status()
                ref_text = clean_html_aggressive(decode_response(ref_resp))
                catch = generate_catchphrase(card, ref_text)
                if catch:
                    meta_data[f"{card.lower()}_catch"] = catch
            except Exception as e:
                print(f"REF SCRAPE ERROR ({card}): {e}")
        else:
            meta_data[f"{card.lower()}_url"] = OFFICIAL_LINKS[card]

        if i < len(URLS) - 1:
            time.sleep(2)

    if not final_stores_list:
        final_stores_list = deepcopy(previous_output.get("stores", []))
        print("WARNING: All extraction failed; keeping previous stores data.", flush=True)

    final_output = {
        "meta": meta_data,
        "stores": final_stores_list
    }

    print(f"\n>>> Total items collected: {len(final_stores_list)}", flush=True)

    try:
        with DATA_FILE.open("w", encoding="utf-8") as f:
            json.dump(final_output, f, ensure_ascii=False, indent=2)
        print(f"SUCCESS: 'data.json' created with stores and referral-based meta.", flush=True)
    except Exception as e:
        print(f"FATAL ERROR: Could not write data.json: {e}", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    if "--check-sources" in sys.argv:
        sys.exit(check_sources(cache_only="--cache-only" in sys.argv))
    main()
