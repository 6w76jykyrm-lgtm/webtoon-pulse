#!/usr/bin/env python3
"""Collect unverified Google News RSS metadata for WEBTOON Pulse."""
import datetime as dt
import email.utils
import hashlib
import html
import json
import pathlib
import re
import time
import urllib.error
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
    ('비즈니스·전략', re.compile(
        r'\b(partnership|acquisition|expansion|launch|subscription|membership|'
        r'monetization|business|strategy)\b', re.I)),
    ('콘텐츠·IP', re.compile(
        r'\b(series|episode|chapter|adaptation|anime|new title|originals|'
        r'creator|artist|comic|manhwa|manga)\b', re.I)),
]


def get(url, timeout=12):
    request = urllib.request.Request(
        url, headers={'User-Agent': 'Mozilla/5.0 (WEBTOON Pulse research)'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(2_000_000)


def translate(title):
    """Best-effort translation; never claim that the article body was verified."""
    if re.search(r'[가-힣]', title) and not re.search(r'[A-Za-z]{5}', title):
        return title, 'original_ko'
    providers = [
        ('machine_google', 'https://translate.googleapis.com/translate_a/single?' +
         urllib.parse.urlencode({'client': 'gtx', 'sl': 'auto', 'tl': 'ko',
                                 'dt': 't', 'q': title})),
        ('machine_mymemory', 'https://api.mymemory.translated.net/get?' +
         urllib.parse.urlencode({'q': title[:450], 'langpair': 'en|ko'})),
    ]
    for name, url in providers:
        try:
            data = json.loads(get(url, timeout=7).decode('utf-8'))
            if name == 'machine_google':
                translated = ''.join(
                    part[0] for part in data[0]
                    if part and isinstance(part[0], str)).strip()
            else:
                translated = str((data.get('responseData') or {}).get(
                    'translatedText') or '').strip()
                if data.get('responseStatus') != 200:
                    raise ValueError('MyMemory status: ' + str(data.get('responseStatus')))
            translated = html.unescape(translated)
            if (translated and translated.casefold() != title.casefold()
                    and 'MYMEMORY WARNING' not in translated.upper()
                    and re.search(r'[가-힣]', translated)):
                return translated, name
            print(f'{name}: no usable Korean translation')
        except (OSError, ValueError, IndexError, TypeError, KeyError, AttributeError) as exc:
            print(f'{name} failed: {type(exc).__name__}: {exc}')
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


def published_date(value):
    try:
        parsed = email.utils.parsedate_to_datetime(value)
        return parsed.astimezone(dt.timezone.utc).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return dt.datetime.now(dt.timezone.utc).date().isoformat()


def collect():
    found = []
    seen = set()
    for competitor, query in SEARCHES.items():
        rss_url = 'https://news.google.com/rss/search?' + urllib.parse.urlencode({
            'q': query, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})
        try:
            root = ET.fromstring(get(rss_url, timeout=15))
        except (OSError, ET.ParseError) as exc:
            print(f'RSS fetch failed for {competitor}: {exc}')
            continue
        count = 0
        for item in root.findall('./channel/item'):
            title = html.unescape((item.findtext('title') or '').strip())
            link = (item.findtext('link') or '').strip()
            if not title or not link or not relevant(competitor, title):
                continue
            key = hashlib.sha256(link.encode('utf-8')).hexdigest()[:16]
            if key in seen:
                continue
            seen.add(key)
            source = (item.findtext('source') or '').strip()
            if not source and ' - ' in title:
                source = title.rsplit(' - ', 1)[-1].strip()
            category = classify(title)
            found.append({
                'id': 'rss-' + key,
                'competitor': competitor,
                'type': category,
                'category': category,
                'title': title,
                'publishedAt': published_date(item.findtext('pubDate')),
                'url': link,
                'source': source,
                'verificationStatus': 'unverified',
            })
            count += 1
            if count >= 15:
                break
        print(f'{competitor}: collected {count} relevant headlines')
        time.sleep(0.2)
    found.sort(key=lambda item: item['publishedAt'], reverse=True)
    return found[:40]


def main():
    articles = collect()
    if not articles:
        raise RuntimeError('No RSS articles collected; existing news.json was not overwritten.')
    old = {}
    if OUT.exists():
        try:
            previous = json.loads(OUT.read_text(encoding='utf-8'))
            old = {a.get('title'): a for a in previous.get('articles', [])
                   if isinstance(a, dict) and a.get('translationStatus') in
                   ('machine_google', 'machine_mymemory', 'original_ko')}
        except (OSError, ValueError, TypeError) as exc:
            print(f'Could not reuse old translations: {exc}')
    for index, article in enumerate(articles, 1):
        title = article['title']
        if title in old:
            translated = old[title].get('titleKo', title)
            status = old[title]['translationStatus']
        else:
            translated, status = translate(title)
        article['titleKo'] = translated
        article['translationStatus'] = status
        article['summary'] = (
            'RSS 제목의 자동 번역입니다. 기사 본문과 관련성은 검증되지 않았습니다.'
            if status != 'unavailable' else
            '한국어 번역을 가져오지 못했습니다. RSS 제목 기준 자동 분류이며 기사 본문과 관련성은 검증되지 않았습니다.'
        )
        print(f'Translation {index}/{len(articles)}: {status}')
    payload = {
        'updatedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
        'source': 'Google News RSS metadata (unverified); headline machine translation (unofficial)',
        'articles': articles,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Saved {len(articles)} articles to {OUT}')


if __name__ == '__main__':
    main()
