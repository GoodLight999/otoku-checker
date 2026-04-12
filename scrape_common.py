import re
from collections import OrderedDict

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8,"
        "application/signed-exchange;v=b3;q=0.7"
    ),
    "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
    "Sec-Ch-Ua": '"Google Chrome";v="123", "Not:A-Brand";v="8", "Chromium";v="123"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}

CARD_HEADERS = {
    "MUFG": {
        "Referer": "https://www.cr.mufg.jp/",
        "Sec-Fetch-Site": "same-origin",
    },
    "SMBC": {
        "Referer": "https://www.smbc-card.com/",
    },
}

CONTENT_MARKERS = {
    "SMBC": ("Vポイント", "対象店舗", "マクドナルド"),
    "MUFG": ("三菱UFJ", "対象店舗", "セブン"),
}

MOJIBAKE_MARKERS = (
    "\u00e3",
    "\u00e5",
    "\u00e8",
    "\u00e9",
    "\u00e2\u0080",
    "\u00c2",
)
JP_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")


def headers_for(card_name):
    headers = DEFAULT_HEADERS.copy()
    headers.update(CARD_HEADERS.get(card_name, {}))
    return headers


def build_session():
    retry = Retry(
        total=3,
        connect=3,
        read=3,
        status=3,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
        raise_on_status=False,
    )
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def japanese_char_count(text):
    return len(JP_RE.findall(text or ""))


def mojibake_marker_count(text):
    if not text:
        return 0
    return sum(text.count(marker) for marker in MOJIBAKE_MARKERS)


def text_score(text):
    return japanese_char_count(text) - mojibake_marker_count(text) * 8


def looks_mojibake(text):
    if not text:
        return False
    marker_count = mojibake_marker_count(text)
    return marker_count >= 5 and marker_count > japanese_char_count(text) // 4


def repair_mojibake(text):
    if not looks_mojibake(text):
        return text

    candidates = [text]
    for encoding in ("latin-1", "cp1252"):
        try:
            candidates.append(text.encode(encoding).decode("utf-8"))
        except UnicodeError:
            continue

    return max(candidates, key=text_score)


def _unique(items):
    return [item for item in OrderedDict.fromkeys(item for item in items if item)]


def decode_bytes(raw, headers=None):
    headers = headers or {}
    header_encoding = requests.utils.get_encoding_from_headers(headers)
    apparent = None
    if raw:
        probe = requests.models.Response()
        probe._content = raw
        apparent = probe.apparent_encoding

    encodings = _unique(
        [
            header_encoding if header_encoding and header_encoding.lower() not in ("iso-8859-1", "latin-1") else None,
            apparent,
            "utf-8",
            "cp932",
            "shift_jis",
            header_encoding,
        ]
    )

    candidates = []
    for encoding in encodings:
        try:
            candidates.append(raw.decode(encoding))
        except (LookupError, UnicodeError):
            continue

    if not candidates:
        candidates.append(raw.decode("utf-8", errors="replace"))

    best = max(candidates, key=text_score)
    return repair_mojibake(best)


def decode_response(response):
    return decode_bytes(response.content, response.headers)


def is_useful_content(card_name, text, min_chars=500):
    if not text or len(text) < min_chars:
        return False

    repaired = repair_mojibake(text)
    if looks_mojibake(repaired):
        return False

    markers = CONTENT_MARKERS.get(card_name, ())
    return all(marker in repaired for marker in markers)
