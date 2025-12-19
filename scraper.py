import os
import requests
import json
import time
import re
import sys
import traceback
from google import genai
from google.genai import types

# --- Configuration ---
API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL_ID = os.environ.get("GEMINI_MODEL_ID", "gemini-flash-latest")

# --- Debug Initialization ---
print("--- INITIALIZING SCRAPER ---")
if not API_KEY:
    print("FATAL ERROR: 'GEMINI_API_KEY' environment variable is missing.")
    sys.exit(1)
else:
    print(f"DEBUG: API_KEY loaded (starts with: {API_KEY[:4]}...)")

print(f"DEBUG: Target Model ID: {MODEL_ID}")

client = genai.Client(api_key=API_KEY)

# 【変更点】Jina.ai を経由せず、直接公式サイトを指定
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
    生HTMLからスクリプトやスタイルを除去してトークンを節約し、
    AIが読みやすくする（BeautifulSoupを使わず正規表現で処理）
    """
    # scriptとstyleタグの中身ごと削除
    html_text = re.sub(r'<script.*?>.*?</script>', '', html_text, flags=re.DOTALL | re.IGNORECASE)
    html_text = re.sub(r'<style.*?>.*?</style>', '', html_text, flags=re.DOTALL | re.IGNORECASE)
    # コメント削除
    html_text = re.sub(r'<!--.*?-->', '', html_text, flags=re.DOTALL)
    # 連続する空白や改行を圧縮
    html_text = re.sub(r'\s+', ' ', html_text)
    return html_text[:90000] # 文字数制限（念のため）

def fetch_and_extract(card_name, target_url):
    print(f"\n>>> Processing: {card_name}")
    print(f"DEBUG: Fetching URL: {target_url}")
    
    # 1. コンテンツ取得 (直接アクセス)
    try:
        # ヘッダーを本物のブラウザに近づける
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Referer": "https://www.google.com/"
        }
        resp = requests.get(target_url, headers=headers, timeout=60)
        resp.raise_for_status()
        
        # HTMLクリーニング実行
        raw_html = resp.text
        content = clean_html(raw_html)
        
        print(f"DEBUG: Web content fetched. Original: {len(raw_html)} -> Cleaned: {len(content)} chars")
        
    except Exception as e:
        print(f"ERROR: Failed to fetch web content: {e}")
        return []

    # 2. プロンプト構築 (HTML解析用に微調整)
    prompt = f"""
        You are an expert data analyst for Japanese credit card rewards.
        The input text is RAW HTML from the official website.
        Ignore HTML tags/attributes and extract the visible text information about store rewards.

        【CRITICAL RULES】
        1. **OUTPUT LANGUAGE**: All string values MUST be in **JAPANESE**.
        2. **GROUP NAME**: Extract formal group name (e.g., "ガスト" -> group: "すかいらーくグループ").
        3. **ALIASES**: Generate slang/abbreviations (e.g., "マクド", "セブイレ").
        4. **MUFG SPECIAL**: Append "Amexは条件が異なる可能性があるため公式サイトを確認推奨" to `note` for all MUFG stores.
        5. **URLS**: If a specific store list URL is found (href inside `<a>` tags), extract it to `official_list_url`.

        【Output JSON Schema】
        Return a JSON ARRAY.
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

        Target HTML Content:
        {content}
    """

    print(f"DEBUG: Sending request to Gemini ({MODEL_ID})...")

    # 3. API実行
    try:
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
    except Exception as e:
        print(f"CRITICAL ERROR: Gemini API request raised an exception: {e}")
        traceback.print_exc()
        return []

    # 4. レスポンス検証
    if not response:
        print("ERROR: Response object is None.")
        return []

    try:
        raw_text = response.text
    except ValueError:
        print(f"ERROR: Could not access response.text. Likely BLOCKED.")
        if hasattr(response, 'candidates') and response.candidates:
            print(f"DEBUG: Finish Reason: {response.candidates[0].finish_reason}")
        return []

    print(f"DEBUG: Response received. Length: {len(raw_text)} chars")
    
    # 5. JSONパース
    cleaned_json = clean_json_text(raw_text)
    
    try:
        data = json.loads(cleaned_json)
        print(f"SUCCESS: Extracted {len(data)} items for {card_name}")
        return data
    except json.JSONDecodeError as je:
        print(f"JSON PARSE ERROR: {je}")
        # デバッグダンプ
        with open(f"debug_dump_{card_name}.txt", "w", encoding="utf-8") as f:
            f.write(raw_text)
        return []

# --- Main Logic ---
final_list = []

for card, url in URLS.items():
    items = fetch_and_extract(card, url)
    if items:
        for item in items:
            item["card_type"] = card
            item["source_url"] = OFFICIAL_LINKS[card]
            final_list.append(item)
    else:
        print(f"WARNING: No data found for {card}.")
    
    time.sleep(5)

print(f"\n>>> Total items collected: {len(final_list)}")

try:
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(final_list, f, ensure_ascii=False, indent=2)
    print(f"SUCCESS: 'data.json' created.")
except Exception as e:
    print(f"FATAL ERROR: Could not write data.json: {e}")
