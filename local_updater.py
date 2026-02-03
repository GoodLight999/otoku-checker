import os
import requests
import sys
import datetime
from urllib.parse import urljoin

# --- Configuration ---
# このスクリプトは自宅サーバー(IP制限のない環境)で実行され、
# HTMLを取得してリポジトリにコミット＆プッシュする。

URLS = {
    "SMBC": "https://www.smbc-card.com/mem/wp/vpoint_up_program/index.jsp",
    "MUFG": "https://www.cr.mufg.jp/mufgcard/point/global/save/convenience_store/index.html"
}

CACHE_DIR = "html_cache"

def clean_html_aggressive(html_text):
    import re
    if not html_text: return ""
    # 巨大ブロック削除
    blocks_to_kill = r'<(header|footer|nav|noscript|script|style|iframe|svg|aside)[^>]*>.*?</\1>'
    html_text = re.sub(blocks_to_kill, '', html_text, flags=re.DOTALL | re.IGNORECASE)
    html_text = re.sub(r'<!--.*?-->', '', html_text, flags=re.DOTALL)
    # リンク以外削除
    html_text = re.sub(r'<((?!a\s)[a-z0-9]+)\s+[^>]*>', r'<\1>', html_text, flags=re.IGNORECASE)
    
    attrs_to_remove = ['class', 'id', 'style', 'target', 'rel', 'onclick', 'data-[a-z0-9-]+', 'aria-[a-z-]+', 'role']
    for attr in attrs_to_remove:
        html_text = re.sub(r'\s+' + attr + r'="[^"]*"', '', html_text, flags=re.IGNORECASE)
        html_text = re.sub(r'\s+' + attr + r"='[^']*'", '', html_text, flags=re.IGNORECASE)

    tags_to_strip = ['div', 'span', 'section', 'article', 'main', 'body', 'html', 'head']
    for tag in tags_to_strip:
        html_text = re.sub(r'<' + tag + r'[^>]*>', '', html_text, flags=re.IGNORECASE)
        html_text = re.sub(r'</' + tag + r'>', '\n', html_text, flags=re.IGNORECASE)

    html_text = re.sub(r'\n+', '\n', html_text)
    html_text = re.sub(r' +', ' ', html_text)
    return html_text[:95000].strip()

def fetch_and_save(name, url):
    print(f"Fetching {name} from {url}...")
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
             "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            "Sec-Ch-Ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1"
        }
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        
        # HTMLを軽量化してから保存
        content = clean_html_aggressive(resp.text)
        
        # 保存
        filepath = os.path.join(CACHE_DIR, f"{name}.html")
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Saved {name} to {filepath} ({len(content)} chars)")
        return True
    except Exception as e:
        print(f"Error fetching {name}: {e}")
        return False

def main():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)
        
    success_count = 0
    for name, url in URLS.items():
        if fetch_and_save(name, url):
            success_count += 1
            
    if success_count > 0:
        print("Updates found. Ready to commit.")
    else:
        print("No updates or errors occurred.")

if __name__ == "__main__":
    main()
