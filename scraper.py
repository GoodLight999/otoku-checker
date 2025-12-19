import os
import requests
import json
import time
from google import genai

# --- 設定 ---
API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)

def get_best_flash_model():
    latest_alias = "gemini-flash-latest"
    try:
        info = client.models.get(model=latest_alias)
        if "gemini-3" in info.name.lower():
            return latest_alias
        else:
            return "gemini-3-flash-preview"
    except:
        return "gemini-3-flash-preview"

MODEL_ID = get_best_flash_model()

# ターゲットURL
URLS = {
    "SMBC": "https://r.jina.ai/https://www.smbc-card.com/mem/wp/vpoint_up_program/index.jsp",
    "MUFG": "https://r.jina.ai/https://www.cr.mufg.jp/mufgcard/point/global/save/convenience_store/index.html"
}

def fetch_and_extract(card_name, target_url):
    print(f"🔍 {card_name}を解析中...")
    try:
        content = requests.get(target_url, timeout=30).text
        
        prompt = f"""
        Extract real-world store rewards for {card_name} from the text. 
        Return ONLY a JSON array.
        Fields: name, rate, aliases (list of nicknames), caution (polite note on conditions), url.
        Text: {content[:15000]}
        """
        
        time.sleep(2) # 無料枠のレート制限対策
        response = client.models.generate_content(model=MODEL_ID, contents=prompt)
        raw_text = response.text.strip()
        
        # Markdownの除去
        if "```json" in raw_text:
            raw_text = raw_text.split("```json")[1].split("```")[0].strip()
        elif "```" in raw_text:
            raw_text = raw_text.split("```")[1].split("```")[0].strip()
            
        return json.loads(raw_text)
    except Exception as e:
        print(f"❌ {card_name}でエラー: {e}")
        return []

# メイン処理
final_data = []
for card, url in URLS.items():
    data = fetch_and_extract(card, url)
    for item in data:
        item["card_type"] = card
    final_data.extend(data)

# ファイル書き出し (これが重要！)
with open("data.json", "w", encoding="utf-8") as f:
    json.dump(final_data, f, ensure_ascii=False, indent=2)

print(f"✅ data.json に {len(final_data)} 件のデータを保存しました。")
