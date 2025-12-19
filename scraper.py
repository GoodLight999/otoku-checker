import os
import requests
import json
import time
import re
import sys
from google import genai
from google.genai.errors import ClientError

# --- Configuration ---
API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL_ID = os.environ.get("GEMINI_MODEL_ID", "gemini-flash-latest")

# --- Debug Initialization ---
print("--- INITIALIZING SCRAPER (RETRY ENHANCED) ---")
if not API_KEY:
    print("FATAL ERROR: 'GEMINI_API_KEY' environment variable is missing.")
    sys.exit(1)

client = genai.Client(api_key=API_KEY)

URLS = {
    "SMBC": "https://www.smbc-card.com/mem/wp/vpoint_up_program/index.jsp",
    "MUFG": "https://www.cr.mufg.jp/mufgcard/point/global/save/convenience_store/index.html"
}

OFFICIAL_LINKS = {
    "SMBC": "https://www.smbc-card.com/mem/wp/vpoint_up_program/index.jsp",
    "MUFG": "https://www.cr.mufg.jp/mufgcard/point/global/save/convenience_store/index.html"
}

def clean_json_text(text):
    """AI出力からJSON部分を抽出"""
    if not text: return "[]"
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match: return match.group()
    return text.strip()

def clean_html_aggressive(html_text):
    """
    【HTML徹底ダイエット】
    """
    if not html_text: return ""

    # 1. 巨大な不要ブロック削除
    blocks_to_kill = r'<(header|footer|nav|noscript|script|style|iframe|svg|form|aside)[^>]*>.*?</\1>'
    html_text = re.sub(blocks_to_kill, '', html_text, flags=re.DOTALL | re.IGNORECASE)

    # 2. コメント削除
    html_text = re.sub(r'<!--.*?-->', '', html_text, flags=re.DOTALL)

    # 3. リンク(a href)以外のタグ属性を全削除
    html_text = re.sub(r'<((?!a\s)[a-z0-9]+)\s+[^>]*>', r'<\1>', html_text, flags=re.IGNORECASE)
    
    # aタグのゴミ属性削除
    attrs_to_remove = ['class', 'id', 'style', 'target', 'rel', 'onclick', 'data-[a-z0-9-]+', 'aria-[a-z-]+', 'role']
    for attr in attrs_to_remove:
        html_text = re.sub(r'\s+' + attr + r'="[^"]*"', '', html_text, flags=re.IGNORECASE)
        html_text = re.sub(r'\s+' + attr + r"='[^']*'", '', html_text, flags=re.IGNORECASE)

    # 4. 不要な「箱」タグ削除
    tags_to_strip = ['div', 'span', 'section', 'article', 'main', 'body', 'html', 'head']
    for tag in tags_to_strip:
        html_text = re.sub(r'<' + tag + r'[^>]*>', '', html_text, flags=re.IGNORECASE)
        html_text = re.sub(r'</' + tag + r'>', '\n', html_text, flags=re.IGNORECASE)

    # 5. 空白・改行の圧縮
    html_text = re.sub(r'\n+', '\n', html_text)
    html_text = re.sub(r' +', ' ', html_text)
    
    return html_text[:95000].strip()

def fetch_and_extract(card_name, target_url):
    print(f"\n>>> Processing: {card_name}")
    print(f"DEBUG: Fetching URL: {target_url}")
    
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
        resp = requests.get(target_url, headers=headers, timeout=60)
        resp.raise_for_status()
        
        raw_html = resp.text
        content = clean_html_aggressive(raw_html)
        
        orig_len = len(raw_html)
        new_len = len(content)
        ratio = (1 - new_len/orig_len) * 100 if orig_len > 0 else 0
        print(f"DEBUG: HTML optimized. {orig_len} -> {new_len} chars. (Reduced by {ratio:.1f}%)")
        
    except Exception as e:
        print(f"ERROR: Failed to fetch web content: {e}")
        return []

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

    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"DEBUG: Sending request to Gemini... (Attempt {attempt+1}/{max_retries})")
            
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
            # 成功したらループを抜ける
            break 

        except ClientError as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                print(f"WARNING: Rate Limit Hit. Sleeping 5s...")
                time.sleep(5) 
                continue
            else:
                print(f"CRITICAL API ERROR: {e}")
                # 429以外のAPIエラー(権限エラー等)はリトライしても無駄なので諦める
                return []
                
        except Exception as e:
            # 【変更点】Server disconnected などの謎エラーもここで拾ってリトライさせる
            print(f"WARNING: Network/Server Error ({e}). Retrying in 5s...")
            time.sleep(5)
            continue
    else:
        print("ERROR: Failed after max retries.")
        return []

    try:
        raw_text = response.text
        cleaned_json = clean_json_text(raw_text)
        data = json.loads(cleaned_json)
        print(f"SUCCESS: Extracted {len(data)} items for {card_name}")
        return data
    except Exception as e:
        print(f"JSON PARSE ERROR: {e}")
        return []

# --- Main Logic ---
final_list = []

for i, (card, url) in enumerate(URLS.items()):
    items = fetch_and_extract(card, url)
    if items:
        for item in items:
            item["card_type"] = card
            item["source_url"] = OFFICIAL_LINKS[card]
            final_list.append(item)
    
    if i < len(URLS) - 1:
        time.sleep(2)

print(f"\n>>> Total items collected: {len(final_list)}")

try:
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(final_list, f, ensure_ascii=False, indent=2)
    print(f"SUCCESS: 'data.json' created.")
except Exception as e:
    print(f"FATAL ERROR: Could not write data.json: {e}")
