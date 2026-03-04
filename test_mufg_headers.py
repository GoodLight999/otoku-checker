import requests

url = "https://www.cr.mufg.jp/mufgcard/point/global/save/convenience_store/index.html"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Referer": "https://www.cr.mufg.jp/",
    "Sec-Ch-Ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1"
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
