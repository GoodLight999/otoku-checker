import os
import requests
import json
import time
import re
from google import genai

# --- 設定 ---
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
    print(f"🔍 {card_name}を解析中（介護モード実行中）...")
    try:
        content = requests.get(target_url, timeout=30).text
        # プロンプトを強化：読み仮名と例示を大量に
        prompt = f"""
        Extract real-world store rewards for {card_name} from the text. 
        Return ONLY a JSON array of objects.
        
        【JSON Structure】
        - name: Official store name (e.g., "東急ストア")
        - aliases: ALL possible search terms including:
            1. Hiragana reading (e.g., "とうきゅうすとあ")
            2. Katakana reading (e.g., "トウキュウストア")
            3. Common nicknames (e.g., "マック", "マクド")
            4. English names if applicable (e.g., "McDonald's")
        - caution: Polite usage note in Japanese.
        
        【Rules】
        - Ignore online-only shops.
        - Be exhaustive with aliases to help users find stores easily.
        
        Text: {content[:15000]}
        """
        
        time.sleep(2)
        response = client.models.generate_content(model=MODEL_ID, contents=prompt)
        raw_text = response.text.strip()
        
        json_match = re.search(r'\[.*\]', raw_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())
        return []
    except Exception as e:
        print(f"❌ {card_name}でエラー: {e}")
        return []

# 店舗統合ロジック
merged_stores = {}
for card, url in URLS.items():
    raw_data = fetch_and_extract(card, url)
    for item in raw_data:
        name = item["name"]
        if name not in merged_stores:
            merged_stores[name] = {
                "name": name,
                "aliases": item.get("aliases", []),
                "supports": []
            }
        if card not in merged_stores[name]["supports"]:
            merged_stores[name]["supports"].append(card)
        
        # 読み仮名・別称をマージして重複削除
        existing_aliases = set(merged_stores[name]["aliases"])
        existing_aliases.update(item.get("aliases", []))
        merged_stores[name]["aliases"] = list(existing_aliases)

final_list = list(merged_stores.values())
with open("data.json", "w", encoding="utf-8") as f:
    json.dump(final_list, f, ensure_ascii=False, indent=2)

print(f"✅ 介護用データの生成が完了しました: {len(final_list)} 店舗")
