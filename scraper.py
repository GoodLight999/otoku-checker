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
    print(f"DEBUG: Processing {card_name} with {MODEL_ID}...")
    try:
        content = requests.get(target_url, timeout=30).text
        # 例示を大幅に増やし、AIへの指示を徹底強化
        prompt = f"""
        Extract real-world store rewards for {card_name} from the provided text.
        Return ONLY a JSON array of objects.

        【JSON Structure】
        - name: Official store name (e.g., "セブン-イレブン", "ガスト")
        - group: Group name if applicable (e.g., "セブン&アイ", "すかいらーくグループ"). null if none.
        - aliases: LIST of all possible search keywords. 
          MUST include:
          1. Hiragana reading (e.g., "せぶんいれぶん", "がすと", "とうきゅうすとあ")
          2. Katakana reading (e.g., "セブンイレブン", "ガスト", "トウキュウストア")
          3. Common nicknames/abbreviations (e.g., "セブン", "マック", "マクド")
          4. Related sub-brands if they share the same reward (e.g., for "セイコーマート", add "ハセガワストア", "タイエー")
        - caution: Short polite note in Japanese regarding payment methods.

        【Extraction Examples for AI Guidance】
        - Store "マクドナルド" -> aliases: ["まくどなるど", "マクド", "マック", "mcdonalds"]
        - Store "すき家" -> aliases: ["すきや", "スキヤ", "ゼンショー"]
        - Store "東急ストア" -> aliases: ["とうきゅうすとあ", "トウキュウストア", "tokyu"]

        Text Content:
        {content[:15000]}
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

# Execution Logic
final_list = []
for card, url in URLS.items():
    raw_data = fetch_and_extract(card, url)
    for item in raw_data:
        item["card_type"] = card
        final_list.append(item)

# Save to file
with open("data.json", "w", encoding="utf-8") as f:
    json.dump(final_list, f, ensure_ascii=False, indent=2)

print(f"SUCCESS: Generated {len(final_list)} entries in data.json")
