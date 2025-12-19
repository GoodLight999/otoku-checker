import os
import requests
import json
import time
import re
from google import genai

# --- Configuration ---
API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)

# 【厳守】先輩の指定した最強のモデル判定ロジック
def get_best_flash_model():
    latest_alias = "gemini-flash-latest"
    try:
        info = client.models.get(model=latest_alias)
        return latest_alias if "gemini-3" in info.name.lower() else "gemini-3-flash-preview"
    except:
        return "gemini-3-flash-preview"

MODEL_ID = get_best_flash_model()

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
        
        # プロンプト：MUFGのブランド構造と日本語出力を徹底
        prompt = f"""
        You are an expert data analyst for Japanese credit card rewards (Poi-katsu).
        Analyze the text and extract store data properly.

        【CRITICAL RULES】
        1. **OUTPUT LANGUAGE**: All string values MUST be in **JAPANESE**.
        2. **ALIASES (略称)**: Generate rich search keywords.
           - "McDonald's" -> ["マクド", "マック", "Mac", "マクドナルド"]
           - "Seicomart" -> ["セコマ", "セイコーマート"]
           - "Seven-Eleven" -> ["セブン", "セブイレ", "セブンイレブン"]
        
        3. **MUFG SPECIAL ATTENTION**: 
           - MUFG Card Global Point rules are strictly divided into two groups:
             Group A: **[Visa / Mastercard / JCB]**
             Group B: **[American Express]**
           - If a store is eligible for Group A but NOT Group B (or vice versa), you MUST state this in the `note` field.
           - Example Note: "Amexは対象外" or "Visa/Master/JCBのみ対象"

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
                "note": "String (e.g., 'Amexブランドは対象外', '商業施設内は対象外')"
            }},
            "official_list_url": "URL or null"
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
