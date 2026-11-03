#!/usr/bin/env python3
"""Google News RSS search metadata collector. No article text verification or AI summaries."""
import datetime as dt
import email.utils
import json
import pathlib
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "news.json"
SEARCHES = [
    ("webtoon", '"WEBTOON" (comics OR app OR entertainment) when:30d'),
    ("tapas", '"Tapas" (webtoon OR comics OR Kakao) when:30d'),
    ("manta", '"Manta" (webtoon OR comics OR Ridi) when:30d'),
    ("tappytoon", '"Tappytoon" (webtoon OR comics) when:30d'),
]

def fetch(competitor, query):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({
        "q": query, "hl": "en-US", "gl": "US", "ceid": "US:en"})
    request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (WEBTOON Pulse RSS research demo)"})
    with urllib.request.urlopen(request, timeout=25) as response:
        xml = response.read(2_000_000)
    result = []
    for item in ET.fromstring(xml).findall("./channel/item")[:25]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        published = (item.findtext("pubDate") or "").strip()
        source_node = item.find("source")
        source = source_node.text.strip() if source_node is not None and source_node.text else "Google News RSS"
        if not title or not link.startswith("https://"):
            continue
        try:
            date = email.utils.parsedate_to_datetime(published).date().isoformat()
        except (TypeError, ValueError, IndexError):
            continue
        result.append({"id": "rss-" + re.sub(r"[^a-zA-Z0-9]", "", competitor + link)[-60:],
            "competitor": competitor, "type": "RSS 뉴스", "title": title, "titleKo": title,
            "publishedAt": date, "url": link, "source": source,
            "summary": "Google News RSS에 노출된 기사 제목입니다. 원문 내용과 사실관계는 별도 확인이 필요합니다."})
    return result

def main():
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    articles = []
    errors = []
    for competitor, query in SEARCHES:
        try:
            found = fetch(competitor, query)
            print(f"{competitor}: {len(found)} items")
            articles.extend(found)
        except Exception as exc:
            errors.append(f"{competitor}: {type(exc).__name__}: {exc}")
    if not articles:
        raise SystemExit("No RSS items collected; keeping previous data file. " + "; ".join(errors))
    unique = {a["url"]: a for a in articles}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"updatedAt": now, "source": "Google News RSS search metadata (unverified)",
        "articles": sorted(unique.values(), key=lambda a: a["publishedAt"], reverse=True), "errors": errors},
        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {len(unique)} articles; {len(errors)} feed errors")

if __name__ == "__main__":
    main()
