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
    print(f"DEBUG: Processing {card_name} (Strict Official Name Mode)")
    try:
        content = requests.get(target_url, timeout=45).text
        
        # 指示を「意味のある別称」と「正式グループ名」に絞る
        prompt = f"""
        Extract EVERY real-world store for {card_name}. DO NOT summarize.
        Return ONLY a JSON array of objects.

        【Rules】
        - name: Use the exact official store name (e.g., "ガスト", "セブン-イレブン").
        - group: The formal group name (e.g., "すかいらーくグループ", "セブン&アイ・ホールディングス"). null if none.
        - aliases: ONLY include meaningful variations. 
          - Nicknames (e.g., "マック", "マクド")
          - English/Original names (e.g., "McDonald's", "7-Eleven")
          - Related brands (e.g., for "セイコーマート", add "ハセガワストア", "タイエー")
          - DO NOT include simple Hiragana/Katakana conversions of the name itself. The search engine will handle it.
        - caution: Short polite note on conditions.

        Text Content:
        {content[:40000]}
        """
        
        time.sleep(2)
        response = client.models.generate_content(model=MODEL_ID, contents=prompt)
        raw_text = response.text.strip()
        
        json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return []
    except Exception as e:
        print(f"ERROR: {card_name} - {e}")
        return []

final_list = []
for card, url in URLS.items():
    raw_data = fetch_and_extract(card, url)
    for item in raw_data:
        item["card_type"] = card
        final_list.append(item)

with open("data.json", "w", encoding="utf-8") as f:
    json.dump(final_list, f, ensure_ascii=False, indent=2)

print(f"✅ data.json updated.")
