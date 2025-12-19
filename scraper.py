import os
import requests
import json
import time
import re
import sys
from urllib.parse import urljoin  # URL結合用
from google import genai
from google.genai import types
from google.genai.errors import ClientError

# --- Configuration ---
API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL_ID = os.environ.get("GEMINI_MODEL_ID", "gemini-flash-latest")

print(f"--- INITIALIZING DEBUG SCRAPER (MODEL: {MODEL_ID}) ---", flush=True)
if not API_KEY:
    print("FATAL ERROR: 'GEMINI_API_KEY' environment variable is missing.", flush=True)
    sys.exit(1)

# タイムアウト90秒 (オリジナル設定を厳守)
client = genai.Client(
    api_key=API_KEY, 
    http_options=types.HttpOptions(timeout=90000) 
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

# 【マージ】環境変数からリファラルURLを取得
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

def clean_html_aggressive(html_text):
    if not html_text: return ""
    
    # 巨大ブロック削除
    blocks_to_kill = r'<(header|footer|nav|noscript|script|style|iframe|svg|aside)[^>]*>.*?</\1>'
    html_text = re.sub(blocks_to_kill, '', html_text, flags=re.DOTALL | re.IGNORECASE)

    html_text = re.sub(r'', '', html_text, flags=re.DOTALL)

    # リンク以外削除
    html_text = re.sub(r'<((?!a\s)[a-z0-9]+)\s+[^>]*>', r'<\1>', html_text, flags=re.IGNORECASE)
    
    attrs_to_remove = ['class', 'id', 'style', 'target', 'rel', 'onclick', 'data-[a-z0-9-]+', 'aria-[a-z-]+', 'role']
    for attr in attrs_to_remove:
        html_text = re.sub(r'\s+' + attr + r'="[^"]*"', '', html_text, flags=re.IGNORECASE)
        html_text = re.sub(r'\s+' + attr + r"='[^']*'", '', html_text, flags=re.IGNORECASE)

    tags_to_strip = ['div', 'span', 'section', 'article', 'main', 'body', 'html', 'head']
    for tag in tags_to_strip:
        html_text = re.sub(r'<' + tag + r'[^>]*>', '', html_text, flags=re.IGNORECASE)
        html_text = re.sub(r'</' + tag + r'>', '\n', html_text, flags=re.IGNORECASE)

    html_text = re.sub(r'\n+', '\n', html_text)
    html_text = re.sub(r' +', ' ', html_text)
    
    return html_text[:95000].strip()

# 【マージ】リファラルサイトのテキストのみを根拠にする生成関数
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
    print(f"\n>>> Processing: {card_name}", flush=True)
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
        resp = requests.get(target_url, headers=headers, timeout=60)
        resp.raise_for_status()
        
        raw_html = resp.text
        content = clean_html_aggressive(raw_html)
        
        with open(f"debug_input_{card_name}.html", "w", encoding="utf-8") as f:
            f.write(content)
        print(f"DEBUG: Saved input HTML ({len(content)} chars)", flush=True)
        
        if len(content) < 100:
            print("FATAL: Cleaned HTML is empty!", flush=True)
            return []
        
    except Exception as e:
        print(f"ERROR: Failed to fetch web content: {e}", flush=True)
        return []

    # 「完全版プロンプト」（一文字も変えず完全維持）
    prompt = f"""
        You are an expert data analyst for Japanese credit card rewards (Poi-katsu).
        Analyze the text and extract store data properly.

        【CRITICAL RULES】
        1. **OUTPUT LANGUAGE**: All string values MUST be in **JAPANESE**.
        
        2. **GROUP NAME**: You MUST extract the formal group name if applicable.
           - Example: "ガスト" -> group: "すかいらーくグループ"
           - Example: "セブン-イレブン" -> group: null

        3. **ALIASES (略称)**: You MUST generate a rich list of search keywords, including slang.
           - "McDonald's" -> ["マクド", "マック", "Mac", "マクドナルド"]
           - "Seicomart" -> ["セコマ", "セイコーマート"]
           - "Seven-Eleven" -> ["セブン", "セブイレ", "セブンイレブン"]
           - "Starbucks" -> ["スタバ", "スターバックス"]
           - "KFC" -> ["ケンタ", "ケンタッキー"]
        
        4. **MUFG SPECIAL CAUTION (Amex)**: 
           - **CRITICAL**: MUFG American Express rules are often NOT in the text (provided only via images). 
           - For ALL MUFG stores, you MUST append this warning to the `note`: "Amexは条件が異なる可能性があるため公式サイトを確認推奨".
           - Separate rules for Visa/Master/JCB vs Amex if text explicitly mentions it.

        5. **SPECIFIC STORE URLS**:
           - If the text provides a specific URL for a store list (e.g., "サイゼリヤの対象店舗一覧はこちら", "ケンタッキー...はこちら"), EXTRACT that specific URL into `official_list_url`.
           - **Saizeriya (SMBC)**: Must link to the specific store list URL if found.
           - **KFC (SMBC)**: Must link to the specific store list URL if found.
           - If no specific list URL is found, set `official_list_url` to null.

        【Output JSON Schema】
        Return a JSON ARRAY.
        {{
            "name": "Store Name (JAPANESE)",
            "group": "Group Name or null (JAPANESE)",
            "aliases": ["Array", "of", "search", "keywords"],
            "conditions": {{
                "payment_method": "String (e.g., 'スマホタッチ決済のみ', '物理カードOK')",
                "mobile_order": "String (e.g., '対象外', '公式アプリのみ対象')",
                "delivery": "String (e.g., '対象外', '自社デリバリーは対象')",
                "note": "String (e.g., 'Amexは要確認')"
            }},
            "official_list_url": "Specific Store List URL or null"
        }}

        Target Text (Cleaned HTML):
        {content}
    """

    max_retries = 2
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
                print(f"WARNING: Rate Limit (429). Sleeping 5s...", flush=True)
                time.sleep(5)
                continue
            else:
                print(f"CRITICAL API ERROR: {e}", flush=True)
                return []
        except Exception as e:
            print(f"WARNING: Network/Timeout Error ({e}).", flush=True)
            if attempt < max_retries - 1:
                print("Retrying in 5s...", flush=True)
                time.sleep(5)
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
    # 1. 公式サイトから店舗抽出
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

    # 2. 【マージ】リファラルリンクのテキストのみからキャッチコピーを生成
    ref_url = REFERRAL_URLS.get(card)
    if ref_url and ref_url != "#":
        try:
            ref_resp = requests.get(ref_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            ref_text = clean_html_aggressive(ref_resp.text)
            catch = generate_catchphrase(card, ref_text)
            if catch:
                meta_data[f"{card.lower()}_catch"] = catch
        except Exception as e:
            print(f"REF SCRAPE ERROR ({card}): {e}")

    if i < len(URLS) - 1:
        time.sleep(2)

# 【最重要】出力構造を辞書形式に変更して保存
final_output = {
    "meta": meta_data,
    "stores": final_stores_list
}

print(f"\n>>> Total stores: {len(final_stores_list)}, meta generated: {len(meta_data)}", flush=True)

try:
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(final_output, f, ensure_ascii=False, indent=2)
    print(f"SUCCESS: 'data.json' created with stores and referral-based meta.", flush=True)
except Exception as e:
    print(f"FATAL ERROR: Could not write data.json: {e}", flush=True)
