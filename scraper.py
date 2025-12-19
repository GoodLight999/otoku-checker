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
# ここは絶対に変えません
API_KEY = os.environ.get("GEMINI_API_KEY")
# デフォルトは "gemini-flash-latest" に戻しました。
# GitHub Actionsの変数(GEMINI_MODEL_ID)があればそれを優先します。
MODEL_ID = os.environ.get("GEMINI_MODEL_ID", "gemini-flash-latest")

# --- Debug Initialization ---
print("--- INITIALIZING SCRAPER ---")
if not API_KEY:
    print("FATAL ERROR: 'GEMINI_API_KEY' environment variable is missing.")
    # キーがないと絶対動かないのでここで終了させます
    sys.exit(1)
else:
    # セキュリティのためキーの一部だけ表示して確認
    print(f"DEBUG: API_KEY loaded (starts with: {API_KEY[:4]}...)")

print(f"DEBUG: Target Model ID: {MODEL_ID}")

client = genai.Client(api_key=API_KEY)

URLS = {
    "SMBC": "https://r.jina.ai/https://www.smbc-card.com/mem/wp/vpoint_up_program/index.jsp",
    "MUFG": "https://r.jina.ai/https://www.cr.mufg.jp/mufgcard/point/global/save/convenience_store/index.html"
}

OFFICIAL_LINKS = {
    "SMBC": "https://www.smbc-card.com/mem/wp/vpoint_up_program/index.jsp",
    "MUFG": "https://www.cr.mufg.jp/mufgcard/point/global/save/convenience_store/index.html"
}

def clean_json_text(text):
    """
    AIの出力からJSON配列部分を抽出。
    """
    if not text: 
        return "[]"
    
    # Markdownコードブロックの除去
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    
    # '[' から ']' までを抽出
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match: 
        return match.group()
    
    return text.strip()

def fetch_and_extract(card_name, target_url):
    print(f"\n>>> Processing: {card_name}")
    print(f"DEBUG: Fetching URL: {target_url}")
    
    # 1. コンテンツ取得
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        resp = requests.get(target_url, headers=headers, timeout=60)
        resp.raise_for_status() # HTTPエラー(404/500等)なら即例外へ
        content = resp.text
        print(f"DEBUG: Web content fetched successfully. Length: {len(content)} chars")
        
        if len(content) < 500:
            print("WARNING: Content is suspiciously short. Check if the URL is blocked.")
    except Exception as e:
        print(f"ERROR: Failed to fetch web content: {e}")
        return []

    # 2. プロンプト構築（ご指定の高機能版）
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

        Target Text:
        {content[:80000]}
    """

    print(f"DEBUG: Sending request to Gemini ({MODEL_ID})...")

    # 3. API実行
    try:
        response = client.models.generate_content(
            model=MODEL_ID, 
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "temperature": 0.0, # 安定化のため0にする
                # Safety Filterによるブロック回避
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

    # 4. レスポンス検証（ここがデバッグの重要ポイント）
    if not response:
        print("ERROR: Response object is None.")
        return []

    # テキスト取り出しを試みる（ブロック時はここで例外が出る場合がある）
    try:
        raw_text = response.text
        if not raw_text:
            print("ERROR: response.text is empty.")
            return []
    except ValueError as ve:
        print(f"ERROR: Could not access response.text. Likely BLOCKED by safety filter.")
        # 理由があれば表示
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
        print("--- RAW RESPONSE START ---")
        print(raw_text[:500] + "...") # 冒頭500文字を表示
        print("--- RAW RESPONSE END ---")
        
        # デバッグ用にファイルにダンプする
        dump_file = f"debug_dump_{card_name}.txt"
        with open(dump_file, "w", encoding="utf-8") as f:
            f.write(raw_text)
        print(f"DEBUG: Saved raw invalid JSON to {dump_file} for inspection.")
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
        print(f"WARNING: No data found for {card}. Check logs.")
    
    time.sleep(5)

print(f"\n>>> Total items collected: {len(final_list)}")

# JSON保存
try:
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(final_list, f, ensure_ascii=False, indent=2)
    print(f"SUCCESS: 'data.json' created with {len(final_list)} entries.")
except Exception as e:
    print(f"FATAL ERROR: Could not write data.json: {e}")
