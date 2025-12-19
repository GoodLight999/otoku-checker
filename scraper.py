import os
import requests
import json
import time
import re
from google import genai

# --- Configuration ---
API_KEY = os.environ.get("GEMINI_API_KEY")
# GitHub Actionsの変数からモデルIDを取得（デフォルトはlatest）
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

def fetch_and_extract(card_name, target_url):
    print(f"DEBUG: Analyzing {card_name} data using {MODEL_ID}...")
    try:
        content = requests.get(target_url, timeout=60).text
        
        # プロンプト：Amex警告とURL抽出を強化
        prompt = f"""
        You are an expert data analyst for Japanese credit card rewards.
        Analyze the text and extract store data properly.

        【CRITICAL RULES】
        1. **OUTPUT LANGUAGE**: All string values MUST be in **JAPANESE**.
        2. **ALIASES (略称)**: Generate rich search keywords.
           - "McDonald's" -> ["マクド", "マック", "Mac", "マクドナルド"]
           - "Seven-Eleven" -> ["セブン", "セブイレ", "セブンイレブン"]

        3. **MUFG SPECIAL CAUTION (Amex)**: 
           - **CRITICAL**: MUFG American Express rules are often NOT in the text (provided only via images). 
           - For ALL MUFG stores, you MUST append this warning to the `note`: "Amexは条件が異なる可能性があるため公式サイトを確認推奨".
           - Do not assume Amex eligibility unless explicitly stated in text.

        4. **SPECIFIC STORE URLS**:
           - If the text provides a specific URL for a store list (e.g., "サイゼリヤの対象店舗一覧はこちら", "ケンタッキー...はこちら"), EXTRACT that specific URL into `official_list_url`.
           - **Saizeriya (SMBC)**: Must link to the specific store list URL if found.
           - **KFC (SMBC)**: Must link to the specific store list URL if found.
           - If no specific list URL is found, set `official_list_url` to null (do NOT use the general campaign URL).

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
                "note": "String (e.g., '商業施設内は対象外。Amexは要確認')"
            }},
            "official_list_url": "Specific Store List URL or null"
        }}

        Target Text:
        {content[:60000]}
        """
        
        response = client.models.generate_content(
            model=MODEL_ID, 
            contents=prompt,
            config={"response_mime_type": "application/json"}
        )
        
        return json.loads(response.text)

    except Exception as e:
        print(f"ERROR: {card_name} extraction failed: {e}")
        return []

final_list = []
for card, url in URLS.items():
    print(f"Processing {card}...")
    items = fetch_and_extract(card, url)
    for item in items:
        item["card_type"] = card
        item["source_url"] = OFFICIAL_LINKS[card]
        final_list.append(item)
    time.sleep(2)

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(final_list, f, ensure_ascii=False, indent=2)

print(f"SUCCESS: Generated {len(final_list)} entries.")
