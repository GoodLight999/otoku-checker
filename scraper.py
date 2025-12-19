import os
import requests
import json
from google import genai

# 設定
API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)

def get_best_flash_model():
    """
    latestがGemini 3でなければ、明示的にpreviewを指定するズボラ検知関数
    """
    latest_alias = "gemini-flash-latest"
    try:
        # エイリアスの実体をチェック
        info = client.models.get(model=latest_alias)
        # nameが 'models/gemini-3-flash' 等を含んでいない場合、3ではないと判断
        if "gemini-3" in info.name.lower():
            print(f"✨ 良好：{latest_alias} は既に Gemini 3 です。")
            return latest_alias
        else:
            print(f"🍵 警告：{latest_alias} はまだ旧世代です。Gemini 3を直接召喚します。")
            return "gemini-3-flash-preview"
    except Exception as e:
        print(f"⚠️ 判定失敗({e})。安全のため preview を使用します。")
        return "gemini-3-flash-preview"

MODEL_ID = get_best_flash_model()

# --- ここから下のスクレイピング処理 ---
URLS = {
    "SMBC": "https://r.jina.ai/https://www.smbc-card.com/mem/wp/vpoint_up_program/index.jsp",
    "MUFG": "https://r.jina.ai/https://www.cr.mufg.jp/mufgcard/point/global/save/convenience_store/index.html"
}

def fetch_and_extract(card_name, target_url):
    print(f"🚀 {card_name} データを {MODEL_ID} で解析中...")
    text_content = requests.get(target_url).text
    
    prompt = f"""
    以下のテキストから、{card_name}のポイントアップ対象となる「実店舗」を抽出してJSONで出力して。
    - name: 公式名
    - rate: 還元率
    - aliases: 略称（マクドナルド→マックなど）。前方一致で解決するものは不要。
    - caution: 支払い条件（スマホタッチ決済必須等）。慇懃無礼にならない丁寧な日本語で。
    - url: 詳細URL
    テキスト：{text_content[:20000]}
    """
    
    # 課金なしでも429(Rate Limit)を回避するための最低限の配慮
    try:
        response = client.models.generate_content(model=MODEL_ID, contents=prompt)
        raw_json = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(raw_json)
    except Exception as e:
        print(f"💥 解析エラー：{e}")
        return []

# 実行・保存ロジック（以下略）
