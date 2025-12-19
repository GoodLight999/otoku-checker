import os
from google import genai

def check_model_config():
    api_key = os.environ.get("GEMINI_API_KEY")
    # GitHub Actions変数で設定されたID、またはデフォルト
    target_model = os.environ.get("GEMINI_MODEL_ID", "gemini-flash-latest")
    
    print("-" * 30)
    print(f"⚙️  Configured Model ID: {target_model}")
    print("-" * 30)

    client = genai.Client(api_key=api_key)
    
    try:
        # 疎通確認
        response = client.models.generate_content(
            model=target_model,
            contents="PING"
        )
        print("✅ API Connection: Success")
        print(f"💬 Response: {response.text.strip()}")
        
        if "gemini-3" in target_model:
            print("🚀 You are explicitly targeting Gemini 3.0 Series.")
        elif "latest" in target_model:
            print("ℹ️  Using 'latest' alias. Version depends on Google's current mapping.")
            
    except Exception as e:
        print(f"❌ API Error: {e}")
        print("設定されたモデルIDが存在しないか、アクセス権がありません。")

if __name__ == "__main__":
    check_model_config()
