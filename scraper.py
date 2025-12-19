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

print(f"--- INITIALIZING DEBUG SCRAPER (MODEL: {MODEL_ID}) ---")
if not API_KEY:
    print("FATAL ERROR: 'GEMINI_API_KEY' environment variable is missing.")
    sys.exit(1)

# タイムアウト設定
client = genai.Client(api_key=API_KEY, http_options={'timeout': 300})

URLS = {
    "SMBC": "https://www.smbc-card.com/mem/wp/vpoint_up_program/index.jsp",
    "MUFG": "https://www.cr.mufg.jp/mufgcard/point/global/save/convenience_store/index.html"
}

OFFICIAL_LINKS = {
    "SMBC": "https://www.smbc-card.com/mem/wp/vpoint_up_program/index.jsp",
    "MUFG": "https://www.cr.mufg.jp/mufgcard/point/global/save/convenience_store/index.html"
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

    # 【修正】formタグを削除対象から外しました。ページ全体がformで囲まれているケースで全滅するのを防ぐため。
    # 削除対象: header, footer, nav, script, style, iframe, svg, aside (formは除外)
    blocks_to_kill = r'<(header|footer|nav|noscript|script|style|iframe|svg|aside)[^>]*>.*?</\1>'
    html_text = re.sub(blocks_to_kill, '', html_text, flags=re.DOTALL | re.IGNORECASE)

    html_text = re.sub(r'<!--.*?-->', '', html_text, flags=re.DOTALL)

    # タグ属性削除
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

def fetch_and_extract(card_name, target_url):
    print(f"\n>>> Processing: {card_name}")
    
    # 1. コンテンツ取得
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        }
        resp = requests.get(target_url, headers=headers, timeout=60)
        resp.raise_for_status()
        
        raw_html = resp.text
        content = clean_html_aggressive(raw_html)
        
        # 【デバッグ】AIに投げる直前のデータを保存（中身が空ならここで判明する）
        debug_filename = f"debug_input_{card_name}.html"
        with open(debug_filename, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"DEBUG: Saved cleaned HTML to {debug_filename} ({len(content)} chars)")
        
        if len(content) < 100:
            print("FATAL: Cleaned HTML is empty! Regex deleted everything.")
            return []
        
    except Exception as e:
        print(f"ERROR: Failed to fetch web content: {e}")
        return []

    prompt = f"""
        You are an expert data analyst for Japanese credit card rewards (Poi-katsu).
        Analyze the text and extract store data properly.

        【CRITICAL RULES】
        1. **OUTPUT LANGUAGE**: All string values MUST be in **JAPANESE**.
        2. **GROUP NAME**: You MUST extract the formal group name if applicable.
        3. **ALIASES (略称)**: You MUST generate a rich list of search keywords.
        4. **MUFG SPECIAL**: For MUFG, append "Amexは条件が異なる可能性があるため公式サイトを確認推奨" to `note`.
        5. **URLS**: Extract specific store list URLs if found.

        【Output JSON Schema】
        [
          {{
            "name": "Store Name",
            "group": "Group Name or null",
            "aliases": ["keyword1", "keyword2"],
            "conditions": {{
                "payment_method": "String",
                "mobile_order": "String",
                "delivery": "String",
                "note": "String"
            }},
            "official_list_url": "URL or null"
          }}
        ]

        Target Text (Cleaned HTML):
        {content}
    """

    # リトライは最大1回（合計2回）
    max_retries = 2
    response_text = ""

    for attempt in range(max_retries):
        try:
            print(f"DEBUG: Requesting Gemini... (Attempt {attempt+1})")
            
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
                print(f"WARNING: Rate Limit (429). Sleeping 5s...")
                time.sleep(5)
                continue
            else:
                print(f"CRITICAL API ERROR: {e}")
                return []
        except Exception as e:
            print(f"WARNING: Network/Server Error ({e}).")
            if attempt < max_retries - 1:
                time.sleep(5)
                continue
            else:
                return []
    
    # 【デバッグ】AIからの返答を保存
    debug_res_filename = f"debug_response_{card_name}.txt"
    try:
        with open(debug_res_filename, "w", encoding="utf-8") as f:
            f.write(response_text if response_text else "EMPTY_RESPONSE")
        print(f"DEBUG: Saved raw API response to {debug_res_filename}")
    except:
        pass

    try:
        cleaned_json = clean_json_text(response_text)
        data = json.loads(cleaned_json)
        print(f"SUCCESS: Extracted {len(data)} items for {card_name}")
        return data
    except Exception as e:
        print(f"JSON PARSE ERROR: {e}")
        # パース失敗時のデータを保存
        with open(f"debug_error_{card_name}.txt", "w", encoding="utf-8") as f:
            f.write(str(e) + "\n\n" + response_text)
        return []

# --- Main Logic ---
final_list = []

for i, (card, url) in enumerate(URLS.items()):
    items = fetch_and_extract(card, url)
    if items:
        for item in items:
            item["card_type"] = card
            item["source_url"] = OFFICIAL_LINKS[card]
        final_list.extend(items)
    
    if i < len(URLS) - 1:
        time.sleep(2)

print(f"\n>>> Total items collected: {len(final_list)}")

try:
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(final_list, f, ensure_ascii=False, indent=2)
    print(f"SUCCESS: 'data.json' created.")
except Exception as e:
    print(f"FATAL ERROR: Could not write data.json: {e}")
