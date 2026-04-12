import os

from scrape_common import build_session, decode_response, headers_for, is_useful_content

# --- Configuration ---
# このスクリプトは自宅サーバー(IP制限のない環境)で実行され、
# HTMLを取得してリポジトリにコミット＆プッシュする。

URLS = {
    "SMBC": "https://www.smbc-card.com/mem/wp/vpoint_up_program/index.jsp",
    "MUFG": "https://www.cr.mufg.jp/mufgcard/point/global/save/convenience_store/index.html"
}

CACHE_DIR = os.path.join(os.path.dirname(__file__), "html_cache")
SESSION = build_session()

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
    html_text = "\n".join(line.rstrip() for line in html_text.splitlines())
    return html_text[:95000].strip() + "\n"

def fetch_and_save(name, url):
    print(f"Fetching {name} from {url}...")
    try:
        resp = SESSION.get(url, headers=headers_for(name), timeout=30)
        resp.raise_for_status()
        raw_html = decode_response(resp)
        
        # HTMLを軽量化してから保存
        content = clean_html_aggressive(raw_html)
        if not is_useful_content(name, content):
            raise ValueError("Fetched HTML does not include expected official content")
        
        # 保存
        filepath = os.path.join(CACHE_DIR, f"{name}.html")
        with open(filepath, "w", encoding="utf-8", newline="\n") as f:
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
            
    if success_count == len(URLS):
        print("Updates found. Ready to commit.")
    elif success_count > 0:
        print(f"Partial cache update: {success_count}/{len(URLS)} files updated.")
        raise SystemExit(1)
    else:
        print("No cache files were updated.")
        raise SystemExit(1)

if __name__ == "__main__":
    main()
