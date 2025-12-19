import os
import requests
import json
import time
import re
from google import genai
from google.genai import types

# --- Configuration ---
API_KEY = os.environ.get("GEMINI_API_KEY")
client = genai.Client(api_key=API_KEY)

# モデル選択ロジック
def get_best_flash_model():
    return "gemini-2.0-flash-exp" 

MODEL_ID = get_best_flash_model()

# 読み込み先URL
URLS = {
    "SMBC": "https://r.jina.ai/https://www.smbc-card.com/mem/wp/vpoint_up_program/index.jsp",
    "MUFG": "https://r.jina.ai/https://www.cr.mufg.jp/mufgcard/point/global/save/convenience_store/index.html"
}

def fetch_and_extract(card_name, target_url):
    print(f"DEBUG: Analyzing {card_name} data with Deep Context reasoning...")
    
    try:
        # Jina AI経由でMarkdownを取得
        content = requests.get(target_url, timeout=45).text
        
        # カードごとの厳格な抽出ルール（日本語徹底）
        system_instruction = ""
        if card_name == "SMBC":
            system_instruction = """
            あなたはSMBC「Vポイントアッププログラム」の厳格なデータ監査官です。
            以下のルールに従い、対象店舗情報を抽出してください。
            
            【重要：SMBC抽出ルール】
            1. **決済手段の区別**: 「スマホのタッチ決済」と「モバイルオーダー」を明確に区別してください。
               - 例: スターバックスのように「モバイルオーダーのみ対象」で、店頭タッチは対象外のケースを見逃さないこと。
               - 例: すき家などは両方対象か？ テキストを精査せよ。
            2. **除外条件**: 注釈（※1, ※2など）にある除外店舗や商業施設内の例外を必ず拾ってください。
            3. **サブブランド**: 「ナチュラルローソン」「ローソンストア100」「スシロー To Go」のようなサブブランドも個別に抽出してください。
            4. **詳細リストURL**: もし「サイゼリヤの対象店舗はこちら」のようなリンクがあれば、そのURLを抽出してください。
            """
        elif card_name == "MUFG":
            system_instruction = """
            あなたは三菱UFJカード「グローバルポイント」の厳格なデータ監査官です。
            
            【重要：MUFG抽出ルール】
            1. **決済の罠**: MUFGは条件が非常に複雑です。
               - 物理カード: 基本OK。
               - タッチ決済（カード現物）: 基本OK。
               - Apple Pay: **「QUICPay」のみ対象**のケースがほとんどです。「スマホでのタッチ決済（NFC）」は対象外であることが多いので注意してください。
               - モバイルオーダー: 対象アプリ（Coke ON、ピザハットオンラインなど）を特定してください。
            2. **ブランド別条件**: アメックス(Amex)だけ条件が違う場合は明記してください。
            3. **デリバリー**: UberEats等の他社経由が対象外か確認してください。
            """

        prompt = f"""
        提供されたMarkdownテキストを分析し、対象店舗のリストをJSON形式で作成してください。
        **出力はすべて日本語で行ってください。**（Visaなどの固有名詞を除く）

        【出力スキーマ (JSON List)】
        - name: (String) 正式な店舗名・ブランド名 (例: "マクドナルド", "セブン-イレブン")。
        - group: (String) グループ名 (例: "すかいらーくグループ")。ない場合はnull。
        - aliases: (Array of Strings) 検索用キーワード。ひらがな、カタカナ、略称、サブブランドを含めること (例: ["セブン", "せぶん", "7-11"])。
        - payment_rule: (String) 許可される決済手段の要約 (例: "スマホタッチ・Mobile Order", "物理カード・QUICPay")。
        - caution: (String) **最重要**。注釈や除外条件を日本語で要約。
          - 「スマホレジ不可」「商業施設内は対象外」などを明記。
          - MUFGの場合、「Apple PayはQUICPayのみ」といった罠を必ず記載。
        - url_list: (String) そのブランド専用の店舗一覧URLがあれば記載。なければnull。
        - mobile_order_app: (Boolean) モバイルオーダーアプリが明示的に対象ならtrue。

        【解析対象テキスト】
        {content[:60000]} 
        """
        
        response = client.models.generate_content(
            model=MODEL_ID,
            contents=system_instruction + "\n\n" + prompt, # System Instructionを結合
            config=types.GenerateContentConfig(
                response_mime_type="application/json"
            )
        )
        
        return json.loads(response.text)

    except Exception as e:
        print(f"ERROR: {card_name} extraction failed: {e}")
        return []

# 実行
final_list = []

# 固定リンク
OFFICIAL_URLS = {
    "SMBC": "https://www.smbc-card.com/mem/wp/vpoint_up_program/index.jsp",
    "MUFG": "https://www.cr.mufg.jp/mufgcard/point/global/save/convenience_store/index.html"
}

for card, url in URLS.items():
    raw_data = fetch_and_extract(card, url)
    for item in raw_data:
        item["card_type"] = card
        item["official_program_url"] = OFFICIAL_URLS[card]
        final_list.append(item)

# データを保存
with open("data.json", "w", encoding="utf-8") as f:
    json.dump(final_list, f, ensure_ascii=False, indent=2)

print(f"SUCCESS: Generated {len(final_list)} entries.")
