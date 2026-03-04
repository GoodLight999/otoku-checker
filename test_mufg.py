import requests

url = "https://www.cr.mufg.jp/mufgcard/point/global/save/convenience_store/index.html"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

try:
    print(f"Fetching {url}...")
    resp = requests.get(url, headers=headers, timeout=10)
    print(f"Status Code: {resp.status_code}")
    if resp.status_code != 200:
        print("Failed!")
    else:
        print("Success!")
except Exception as e:
    print(f"Error: {e}")
