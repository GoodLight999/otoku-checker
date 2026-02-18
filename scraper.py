import os
import requests
import json
import time
import re
import sys
from urllib.parse import urljoin
from google import genai
from google.genai import types
from google.genai.errors import ClientError
import trafilatura
from bs4 import BeautifulSoup

# --- Configuration ---
API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL_ID = os.environ.get("GEMINI_MODEL_ID", "gemini-flash-latest")

print(f"--- INITIALIZING DEBUG SCRAPER (MODEL: {MODEL_ID}) ---", flush=True)
if not API_KEY:
    print("FATAL ERROR: 'GEMINI_API_KEY' environment variable is missing.", flush=True)
    sys.exit(1)

# タイムアウト180秒
client = genai.Client(
    api_key=API_KEY,
    http_options=types.HttpOptions(timeout=180000)
)

URLS = {
    "SMBC": "https://www.smbc-card.com/mem/wp/vpoint_up_program/index.jsp",
    "MUFG": "https://www.cr.mufg.jp/mufgcard/point/global/save/convenience_store/index.html"
}

OFFICIAL_LINKS = {
    "SMBC": "https://www.smbc-card.com/mem/wp/vpoint_up_program/index.jsp",
    "MUFG": "https://www.cr.mufg.jp/mufgcard/point/global/save/convenience_store/index.html"
}

# 相対パスを絶対パスに変換するためのベースドメイン定義
BASE_DOMAINS = {
    "SMBC": "https://www.smbc-card.com",
    "MUFG": "https://www.cr.mufg.jp"
}

# 環境変数からリファラルURLを取得 (GitHub ActionsのVariablesから)
REFERRAL_URLS = {
    "SMBC": os.environ.get("SMBC_REFERRAL_URL"),
    "MUFG": os.environ.get("MUFG_REFERRAL_URL")
}

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
    """
    if not html_text:
        return ""
    
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

# リファラルリンクのテキストのみを根拠にする生成関数
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
        response = client.models.generate_content(
            model=MODEL_ID, 
            contents=prompt,
            config={"response_mime_type": "application/json", "temperature": 0.0}
        )
        return json.loads(response.text).get("catch")
    except:
        return None

def fetch_and_extract(card_name, target_url):
    print(f"\n>>> Processing Official: {card_name}", flush=True)
    
    content = ""
    # 1. 既存のrequests + 偽装ヘッダーでの試行
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Sec-Ch-Ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        }
        resp = requests.get(target_url, headers=headers, timeout=60)
        resp.raise_for_status()
        raw_html = resp.text
        content = clean_html_aggressive(raw_html, card_name)
        print(f"DEBUG: Direct fetch successful ({len(content)} chars)", flush=True)

    except Exception as e:
        print(f"WARNING: Direct fetch failed ({e}). Checking for local cache...", flush=True)
        # 2. ローカルキャッシュ（リポジトリ内のファイル）を確認
        # 自宅サーバーから定期的にPushされたHTMLがあればそれを使う
        cache_path = f"html_cache/{card_name}.html"
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    content = f.read()
                print(f"DEBUG: Local cache found and loaded ({len(content)} chars)", flush=True)
            except Exception as cache_e:
                print(f"ERROR: Failed to load local cache: {cache_e}", flush=True)
                return []
        else:
            print(f"ERROR: No local cache found at {cache_path}. Giving up.", flush=True)
            return []

    if len(content) < 100:
        print("FATAL: Content is empty!", flush=True)
        return []
        
    with open(f"debug_input_{card_name}.html", "w", encoding="utf-8") as f:
        f.write(content)
        
    # 完全版プロンプト (商業施設内の対象外警告を強化)
    prompt = f"""
        You are an expert data analyst for Japanese credit card rewards (Poi-katsu).
        Analyze the text and extract store data properly.

        【CRITICAL RULES】
        1. **OUTPUT LANGUAGE**: All string values MUST be in **JAPANESE**.
        
        2. **GROUP NAME**: You MUST extract the formal group name if applicable.
           - Example: "ガスト" -> group: "すかいらーくグループ"
           - Example: "セブン-イレブン" -> group: null

        3. **ALIASES (略称)**: You MUST generate a rich list of search keywords, including slang.
           - **KANJI TO HIRAGANA**: If the store name contains Kanji, you MUST include the Hiragana reading in aliases.
           - "吉野家" -> ["よしのや", "吉牛", "よしの家"]
           - "McDonald's" -> ["マクド", "マック", "Mac", "マクドナルド"]
           - "Seicomart" -> ["セコマ", "セイコーマート", "せいこーまーと"]
           - "Seven-Eleven" -> ["セブン", "セブイレ", "セブンイレブン"]
        
        4. **MUFG SPECIAL CAUTION (Amex)**: 
           - **CRITICAL**: MUFG American Express rules are often NOT in the text (provided only via images). 
           - For ALL MUFG stores, you MUST append this warning to the `note`: "Amexは条件が異なる可能性があるため公式サイトを確認推奨".
           - Separate rules for Visa/Master/JCB vs Amex if text explicitly mentions it.

        5. **SPECIFIC STORE URLS**:
           - If the text provides a specific URL for a store list (e.g., "サイゼリヤの対象店舗一覧はこちら", "ケンタッキー...はこちら"), EXTRACT that specific URL into `official_list_url`.
           - **Saizeriya (SMBC)**: Must link to the specific store list URL if found.
           - **KFC (SMBC)**: Must link to the specific store list URL if found.
           - If no specific list URL is found, set `official_list_url` to null.
           
        6. **COMMERCIAL FACILITIES (商業施設)**:
           - Check for footnotes or warnings about "commercial facilities" (商業施設).
           - If the text mentions that stores inside commercial facilities/stations are excluded, you MUST explicitly include "商業施設内の店舗は対象外の場合あり" in the `note`.
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
            
            response = client.models.generate_content(
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
                return []
        except Exception as e:
            print(f"WARNING: Network/Timeout Error ({e}).", flush=True)
            if attempt < max_retries - 1:
                print("Retrying in 20s...", flush=True)
                time.sleep(20)
                continue
            else:
                return []
    
    try:
        with open(f"debug_response_{card_name}.txt", "w", encoding="utf-8") as f:
            f.write(response_text if response_text else "EMPTY_RESPONSE")
    except:
        pass

    try:
        cleaned_json = clean_json_text(response_text)
        data = json.loads(cleaned_json)
        print(f"SUCCESS: Extracted {len(data)} items for {card_name}", flush=True)
        return data
    except Exception as e:
        print(f"JSON PARSE ERROR: {e}", flush=True)
        with open(f"debug_error_{card_name}.txt", "w", encoding="utf-8") as f:
            f.write(str(e) + "\n\n" + response_text)
        return []

# --- Main Logic ---
final_stores_list = []
meta_data = {}

for i, (card, url) in enumerate(URLS.items()):
    # 1. 公式サイトから店舗情報を抽出
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

    # 2. リファラルサイトの情報処理 (URL保存 ＆ キャッチコピー生成)
    ref_url = REFERRAL_URLS.get(card)
    
    # 修正ポイント: 環境変数のURLをmetaデータに必ず保存する
    if ref_url and ref_url != "#":
        meta_data[f"{card.lower()}_url"] = ref_url
        
        try:
            # こちらも偽装しておく
            ref_resp = requests.get(ref_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            ref_text = clean_html_aggressive(ref_resp.text, card)
            catch = generate_catchphrase(card, ref_text)
            if catch:
                meta_data[f"{card.lower()}_catch"] = catch
        except Exception as e:
            print(f"REF SCRAPE ERROR ({card}): {e}")
    else:
        # リファラルがない場合は公式へのリンクなどを入れておく（空だと困る場合への保険）
        meta_data[f"{card.lower()}_url"] = OFFICIAL_LINKS[card]

    if i < len(URLS) - 1:
        time.sleep(2)

# 出力構造を辞書形式に変更し、HTML側の参照を成立させる
final_output = {
    "meta": meta_data,
    "stores": final_stores_list
}

print(f"\n>>> Total items collected: {len(final_stores_list)}", flush=True)

try:
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)
    print(f"SUCCESS: 'data.json' created with stores and referral-based meta.", flush=True)
except Exception as e:
    print(f"FATAL ERROR: Could not write data.json: {e}", flush=True)
