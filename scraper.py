import os
import requests
import json
import time
import re
from google import genai

# --- Configuration ---
API_KEY = os.environ.get("GEMINI_API_KEY")
# デフォルトは "gemini-flash-latest" に戻しました。
# GitHub Actionsの変数(GEMINI_MODEL_ID)があればそれを優先します。
MODEL_ID = os.environ.get("GEMINI_MODEL_ID", "gemini-flash-latest")

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
    AIの出力からJSON配列部分だけを外科手術のように正確に切り出す。
    以前の r'\[.*\]' は、前置きに [Note] とかあると死ぬため、
    「[{」で始まり「}]」で終わるパターンを優先的に探す。
    """
    # 1. まずMarkdown記法を除去
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    
    # 2. 「配列の中にオブジェクトが入っている」構造 ( [{ ... }] ) を探す
    #    re.DOTALL で改行も無視してマッチさせる
    match = re.search(r'\[\s*\{.*\}\s*\]', text, re.DOTALL)
    if match:
        return match.group()
    
    # 3. それで見つからなければ、単純な [] を探す（フォールバック）
    match_simple = re.search(r'\[.*\]', text, re.DOTALL)
    if match_simple:
        return match_simple.group()
        
    return text.strip()

def fetch_and_extract(card_name, target_url):
    print(f"DEBUG: Analyzing {card_name} data using {MODEL_ID}...")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        content = requests.get(target_url, headers=headers, timeout=60).text
        
        if not content or len(content) < 100:
            print(f"FATAL: Empty content for {card_name}")
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

        Target Text:
        {content[:80000]}
        """
        
        response = client.models.generate_content(
            model=MODEL_ID, 
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        
        cleaned_json = clean_json_text(response.text)
        data = json.loads(cleaned_json)
        
        print(f"SUCCESS: Extracted {len(data)} items for {card_name}")
        return data

    except Exception as e:
        print(f"ERROR: {card_name} extraction failed: {e}")
        if 'response' in locals() and hasattr(response, 'text'):
            print(f"Raw Response Dump: {response.text[:200]}...") 
        return []

# --- Main Execution ---
final_list = []
for card, url in URLS.items():
    items = fetch_and_extract(card, url)
    for item in items:
        item["card_type"] = card
        item["source_url"] = OFFICIAL_LINKS[card]
        final_list.append(item)
    time.sleep(2)

if not final_list:
    print("WARNING: Final list is empty. Check the logs above.")

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(final_list, f, ensure_ascii=False, indent=2)

print(f"COMPLETE: Generated {len(final_list)} entries.")
