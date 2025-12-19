import os
from google import genai

def summon_model_info():
    # 2025年最新のUnified SDKクライアント
    client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    
    # チェックしたいエイリアス
    target_alias = "gemini-flash-latest"
    
    try:
        # 1. APIの疎通確認（生存確認）
        response = client.models.generate_content(
            model=target_alias,
            contents="PING"
        )
        print("✅ API Status: Alive (Connection Successful)")
        
        # 2. エイリアスの中身（実体）を特定する
        model_info = client.models.get(model=target_alias)
        
        print("-" * 30)
        print(f"📡 Alias: {target_alias}")
        print(f"🆔 Real Model ID: {model_info.name}") # ここで「実体」が判明します
        print(f"🧠 Version: {model_info.version}")
        print(f"📝 Description: {model_info.description}")
        print("-" * 30)

        if "gemini-3" in model_info.name:
            print("✨ 朗報です。最新のGemini 3が召喚されています。")
        else:
            print("🍵 まだGemini 2.5のようですね。手動で 'gemini-3-flash-preview' を指定しましょうか？")

    except Exception as e:
        print(f"❌ API Error: {e}")

if __name__ == "__main__":
    summon_model_info()
