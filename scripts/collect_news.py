#!/usr/bin/env python3
"""Collect Google News RSS headlines for WEBTOON Pulse (not verified article text)."""
import datetime as dt
import email.utils
import hashlib
import json
import pathlib
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / 'data' / 'news.json'

SEARCHES = {
    'webtoon': 'WEBTOON (comics OR app OR entertainment) when:30d',
    'tapas': 'Tapas (webtoon OR comics OR Kakao) when:30d',
    'manta': 'Manta (webtoon OR comics OR Ridibooks OR Ridi) when:30d',
    'tappytoon': 'Tappytoon (webtoon OR comics) when:30d',
}

PATTERNS = {
    'webtoon': re.compile(r'\bwebtoon\b', re.I),
    'tapas': re.compile(r'\btapas\b', re.I),
    'manta': re.compile(r'\bmanta\b', re.I),
    'tappytoon': re.compile(r'\btappytoon\b', re.I),
}
COMICS_CONTEXT = re.compile(
    r'\b(webtoon|webcomics?|comics?|manhwa|manga|graphic novel|episodes?|chapters?|'
    r'creators?|kakao entertainment|ridibooks|ridi|tappytoon|digital comics?)\b', re.I)
UNRELATED = {
    'tapas': re.compile(r'\b(restaurants?|recipes?|food|dishes|bars?|wine|spanish cuisine)\b', re.I),
    'manta': re.compile(r'\b(manta rays?|diving|snorkeling|ocean|marine|fish|resort)\b', re.I),
}
FINANCE = re.compile(
    r'\b(financial results|stock|shares|nasdaq|analyst|investor|price target|'
    r'EPS|quarterly earnings|stock price)\b', re.I)
CATEGORIES = [
    ('비즈니스·전략', re.compile(r'\b(partnership|acquisition|expansion|launch|subscription|'
                                   r'membership|monetization|business|strategy)\b', re.I)),
    ('콘텐츠·IP', re.compile(r'\b(series|episode|chapter|adaptation|anime|new title|'
                              r'originals|creator|artist|comic|manhwa|manga)\b', re.I)),
]


def get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (WEBTOON Pulse research)'})
    with urllib.request.urlopen(request, timeout=18) as response:
        return response.read(2_000_000)


def translate(title):
    """Best-effort unofficial translation; original title remains on failure."""
    try:
        url = 'https://translate.googleapis.com/translate_a/single?' + urllib.parse.urlencode({
            'client': 'gtx', 'sl': 'auto', 'tl': 'ko', 'dt': 't', 'q': title})
        result = json.loads(get(url).decode('utf-8'))
        korean = ''.join(part[0] for part in result[0] if part and isinstance(part[0], str)).strip()
        if korean and korean.casefold() != title.casefold():
            return korean, 'machine'
    except (OSError, ValueError, IndexError, TypeError, KeyError):
        pass
    return title, 'unavailable'


def classify(headline):
    for category, pattern in CATEGORIES:
        if pattern.search(headline):
            return category
    return '기타 업계 뉴스'


def relevant(competitor, headline):
    if not PATTERNS[competitor].search(headline):
        return False
    if FINANCE.search(headline):
        return False
    if competitor in UNRELATED and UNRELATED[competitor].search(headline):
        return False
    if competitor in ('tapas', 'manta') and not COMICS_CONTEXT.search(headline):
        return False
    return True


def fetch(competitor, query):
    url = 'https://news.google.com/rss/search?' + urllib.parse.urlencode({
        'q': query, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})
    items = ET.fromstring(get(url)).findall('./channel/item')
    results = []
    for item in items[:50]:
        title = (item.findtext('title') or '').strip()
        link = (item.findtext('link') or '').strip()
        source_node = item.find('source')
        source = source_node.text.strip() if source_node is not None and source_node.text else 'Google News RSS'
        if not title or not link.startswith('https://'):
            continue
        headline = title.rsplit(' - ', 1)[0]
        if not relevant(competitor, headline):
            continue
        try:
            published = email.utils.parsedate_to_datetime(item.findtext('pubDate')).date().isoformat()
        except (TypeError, ValueError, IndexError):
            continue
        category = classify(headline)
        results.append({
            'id': 'rss-' + hashlib.sha256(link.encode()).hexdigest()[:16],
            'competitor': competitor, 'type': category, 'category': category,
            'title': title, 'publishedAt': published, 'url': link,
            'source': source, 'verificationStatus': 'unverified',
        })
    return results


def main():
    articles, errors = [], []
    for competitor, query in SEARCHES.items():
        try:
            found = fetch(competitor, query)
            print(f'{competitor}: {len(found)} relevant headline candidates')
            articles.extend(found)
        except Exception as exc:
            errors.append(f'{competitor}: {type(exc).__name__}: {exc}')
    if not articles:
        raise SystemExit('No matching RSS items; existing data preserved. ' + '; '.join(errors))

    unique = {article['url']: article for article in articles}
    for article in unique.values():
        article['titleKo'], article['translationStatus'] = translate(article['title'])
        article['summary'] = (
            '제목은 자동 번역되었습니다. ' if article['translationStatus'] == 'machine'
            else '한국어 번역을 가져오지 못했습니다. '
        ) + 'RSS 제목 기준 자동 분류이며 기사 본문과 관련성은 검증되지 않았습니다.'
        time.sleep(0.15)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        'updatedAt': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
        'source': 'Google News RSS metadata (unverified); headline machine translation (unofficial)',
        'articles': sorted(unique.values(), key=lambda a: a['publishedAt'], reverse=True),
        'errors': errors,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Saved {len(unique)} headlines; translated '
          f'{sum(a["translationStatus"] == "machine" for a in unique.values())}; '
          f'feed errors {len(errors)}')


if __name__ == '__main__':
    main()
