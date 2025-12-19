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
    print(f"DEBUG: Extracting {card_name} stores from {target_url}")
    try:
        # 読み込み範囲を5万文字に拡大（欠損防止）
        content = requests.get(target_url, timeout=45).text
        
        # 網羅性を最優先し、AIに「全店舗の出力」を強制
        prompt = f"""
        Extract EVERY SINGLE store reward for {card_name} listed in the text below. 
        DO NOT omit, summarize, or truncate. I need an exhaustive list.
        
        Return ONLY a JSON array of objects.
        
        【JSON Structure】
        - name: Official store name.
        - group: Parent group name (e.g., "すかいらーく", "セブン&アイ") if mentioned.
        - aliases: Exhaustive search terms. Include:
            1. Hiragana reading (MUST include for every store)
            2. Katakana reading
            3. Common nicknames
            4. Sub-brands sharing the same reward (e.g., for "セイコーマート", include "ハセガワストア", "タイエー")
        - caution: Short payment condition note.

        Text Content:
        {content[:50000]}
        """
        
        time.sleep(2)
        response = client.models.generate_content(model=MODEL_ID, contents=prompt)
        raw_text = response.text.strip()
        
        json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            print(f"SUCCESS: Extracted {len(data)} items for {card_name}")
            return data
        return []
    except Exception as e:
        print(f"ERROR: Failed to process {card_name}: {e}")
        return []

# 各カードのデータを独立して保持（セブンが2回出る仕様を確定）
final_list = []
for card, url in URLS.items():
    raw_data = fetch_and_extract(card, url)
    for item in raw_data:
        item["card_type"] = card
        final_list.append(item)

# Save results
with open("data.json", "w", encoding="utf-8") as f:
    json.dump(final_list, f, ensure_ascii=False, indent=2)
