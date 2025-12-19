import os
import requests
import json
import time
import re
from google import genai

# --- Configuration ---
API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)

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

def fetch_and_extract(card_name, target_url):
    print(f"DEBUG: Analyzing {card_name} data with high-context reasoning...")
    try:
        # 読み込み範囲を最大化し、情報の取りこぼしを防ぐ
        content = requests.get(target_url, timeout=45).text
        
        prompt = f"""
        Analyze the text and extract EVERY store reward for {card_name}. 
        You must interpret the specific conditions for each brand.

        【Output JSON Schema】
        - name: Official store name.
        - group: Formal group name (e.g., "すかいらーくグループ").
        - aliases: Search keywords. INCLUDE Hiragana, Katakana, English, and SUB-BRANDS (e.g., for "セイコーマート", add "ハセガワストア", "タイエー").
        - mobile_order: boolean (true if mobile order is explicitly mentioned as a reward target).
        - touch_only: boolean (true if ONLY smartphone touch payment is eligible for max reward).
        - caution: Specific condition note (e.g., "物理カードOK", "Apple Pay必須").

        【Contextual Reasoning Rules for {card_name}】
        - If SMBC: Check if smartphone touch payment (Apple/Google Pay) is required for the 7%+.
        - If MUFG: Check if physical card use is eligible (Usually YES for MUFG).
        - Identify if mobile order (e.g., McDonald's Mobile Order) is eligible.

        DO NOT summarize. Extract every brand like "Seicomart", "Hasegawa Store", etc.
        Return ONLY a JSON array.

        Text Content:
        {content[:45000]}
        """
        
        time.sleep(2)
        response = client.models.generate_content(model=MODEL_ID, contents=prompt)
        raw_text = response.text.strip()
        
        json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return []
    except Exception as e:
        print(f"ERROR: {card_name} extraction failed: {e}")
        return []

# 実行・保存
final_list = []
for card, url in URLS.items():
    raw_data = fetch_and_extract(card, url)
    for item in raw_data:
        item["card_type"] = card
        final_list.append(item)

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(final_list, f, ensure_ascii=False, indent=2)

print(f"SUCCESS: Generated {len(final_list)} entries.")
