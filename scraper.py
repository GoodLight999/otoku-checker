import os
import requests
import json
import time
import re
import sys
import traceback
from google import genai
from google.genai import types
from google.genai.errors import ClientError

# --- Configuration ---
API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL_ID = os.environ.get("GEMINI_MODEL_ID", "gemini-flash-latest")

# --- Debug Initialization ---
print("--- INITIALIZING SCRAPER ---")
if not API_KEY:
    print("FATAL ERROR: 'GEMINI_API_KEY' environment variable is missing.")
    sys.exit(1)

client = genai.Client(api_key=API_KEY)

# Jinaを経由せず直接アクセス
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

def clean_html(html_text):
    """
    プロンプトをリッチにする分、入力データ（HTML）を徹底的にダイエットさせる。
    タグの構造（ul, li, div, h3）は残すが、classやstyleなどの属性は全て削除してトークンを節約する。
    """
    # 1. script, style, コメント除去
    html_text = re.sub(r'<script.*?>.*?</script>', '', html_text, flags=re.DOTALL | re.IGNORECASE)
    html_text = re.sub(r'<style.*?>.*?</style>', '', html_text, flags=re.DOTALL | re.IGNORECASE)
    html_text = re.sub(r'<!--.*?-->', '', html_text, flags=re.DOTALL)
    
    # 2. タグの属性を削除 (<div class="..."> -> <div>)
    #    <タグ名(スペース)...> のパターンを <タグ名> に置換
    html_text = re.sub(r'<([a-zA-Z0-9]+)\s+[^>]*>', r'<\1>', html_text)
    
    # 3. inputタグなどはノイズなので消す
    html_text = re.sub(r'<input[^>]*>', '', html_text, flags=re.IGNORECASE)
    
    # 4. 連続する空白・改行を圧縮
    html_text = re.sub(r'\s+', ' ', html_text)
    
    return html_text[:95000] # 文字数制限

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
        # ここでHTMLを軽量化し、プロンプト分のトークン余地を作る
        content = clean_html(raw_html)
        print(f"DEBUG: Web content fetched & optimized. Original: {len(raw_html)} -> Cleaned: {len(content)} chars")
        
    except Exception as e:
        print(f"ERROR: Failed to fetch web content: {e}")
        return []

    # 【重要】ご指定の完全版プロンプトを使用
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

    # リトライロジック (429エラー対策)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            print(f"DEBUG: Sending request to Gemini... (Attempt {attempt+1}/{max_retries})")
            
            # 安全フィルター全開放・Temperature 0.0 で実行
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
            
            # エラーが出なければループを抜ける
            break 

        except ClientError as e:
            # 429エラー (Resource Exhausted) の場合のみ待機してリトライ
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                print(f"WARNING: Rate Limit Hit (429). Sleeping 60 seconds before retry...")
                time.sleep(60) 
                continue
            else:
                # その他のAPIエラーは即死させる
                print(f"CRITICAL API ERROR: {e}")
                return []
        except Exception as e:
            print(f"UNKNOWN ERROR during API call: {e}")
            return []
    else:
        print("ERROR: Failed after max retries due to Rate Limits.")
        return []

    # レスポンス処理
    try:
        raw_text = response.text
        cleaned_json = clean_json_text(raw_text)
        data = json.loads(cleaned_json)
        print(f"SUCCESS: Extracted {len(data)} items for {card_name}")
        return data
    except Exception as e:
        print(f"JSON PARSE ERROR: {e}")
        # デバッグダンプ
        with open(f"debug_dump_{card_name}.txt", "w", encoding="utf-8") as f:
            f.write(response.text if response else "No response")
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
    
    # 次のカード処理の前に必ず休憩を入れる (レート制限対策)
    if i < len(URLS) - 1:
        print("DEBUG: Cooling down for 30 seconds to respect API limits...")
        time.sleep(30)

print(f"\n>>> Total items collected: {len(final_list)}")

try:
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(final_list, f, ensure_ascii=False, indent=2)
    print(f"SUCCESS: 'data.json' created.")
except Exception as e:
    print(f"FATAL ERROR: Could not write data.json: {e}")
