#!/usr/bin/env python3
"""Collect relevant Google News RSS metadata and best-effort Korean headline translations.
Not article verification or an official translation service.
"""
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
    'webtoon': '"WEBTOON" ("webtoon platform" OR "WEBTOON Entertainment" OR "WEBTOON app") when:30d',
    'tapas': '"Tapas" ("Tapas Entertainment" OR "Tapas webcomics" OR "Tapas comics") when:30d',
    'manta': '"Manta" ("Manta Comics" OR "Manta webtoon" OR "Manta app") when:30d',
    'tappytoon': '"Tappytoon" ("webtoon" OR "comics" OR "platform") when:30d',
}
# Filter for platform context, rather than any mention of a series, a word, or an app name.
CONTEXT = re.compile(r'\b(platform|app|service|subscription|pricing|price|launch|launched|release|released|update|partnership|partner|acquisition|revenue|creator|publisher|publishing|webtoon|webcomics|comic|comics|manga|manhwa|reader|readers|business|investment|growth|licens\w*|entertainment|kakao|ridi)\b', re.I)
PLATFORM = {
    'webtoon': re.compile(r'\bWEBTOON\b', re.I),
    'tapas': re.compile(r'\bTapas\b', re.I),
    'manta': re.compile(r'\bManta\b', re.I),
    'tappytoon': re.compile(r'\bTappytoon\b', re.I),
}
# Exclude obvious unrelated matches. Heuristics can still miss or misclassify articles.
NEGATIVE = {
    'manta': re.compile(r'\bmanta rays?\b|\bmanta ray\b|\bscuba\b|\bocean wildlife\b', re.I),
    'tapas': re.compile(r'\btapas bar\b|\bspanish tapas\b|\btapas restaurant\b|\btapas menu\b', re.I),
}

def get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (WEBTOON Pulse research)'})
    with urllib.request.urlopen(request, timeout=18) as response:
        return response.read(2_000_000)

def translate(title):
    """Unofficial public translation endpoint: may rate-limit or stop working."""
    try:
        url = 'https://translate.googleapis.com/translate_a/single?' + urllib.parse.urlencode({
            'client': 'gtx', 'sl': 'auto', 'tl': 'ko', 'dt': 't', 'q': title})
        result = json.loads(get(url).decode('utf-8'))
        ko = ''.join(x[0] for x in result[0] if x and isinstance(x[0], str)).strip()
        if ko and ko.casefold() != title.casefold():
            return ko, 'machine'
    except (OSError, ValueError, IndexError, TypeError, KeyError):
        pass
    return title, 'unavailable'

def fetch(competitor, query):
    url = 'https://news.google.com/rss/search?' + urllib.parse.urlencode({
        'q': query, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'})
    result = []
    for item in ET.fromstring(get(url)).findall('./channel/item')[:30]:
        title = (item.findtext('title') or '').strip()
        link = (item.findtext('link') or '').strip()
        source_node = item.find('source')
        source = source_node.text.strip() if source_node is not None and source_node.text else 'Google News RSS'
        if not title or not link.startswith('https://'):
            continue
        # Google News appends the publisher name to headlines; use headline part for matching.
        headline = title.rsplit(' - ', 1)[0]
        if not PLATFORM[competitor].search(headline) or not CONTEXT.search(headline):
            continue
        if competitor in NEGATIVE and NEGATIVE[competitor].search(headline):
            continue
        try:
            published = email.utils.parsedate_to_datetime(item.findtext('pubDate')).date().isoformat()
        except (TypeError, ValueError, IndexError):
            continue
        result.append({'id': 'rss-' + hashlib.sha256(link.encode()).hexdigest()[:16],
                       'competitor': competitor, 'type': 'RSS 뉴스', 'title': title,
                       'publishedAt': published, 'url': link, 'source': source})
    return result

def main():
    articles, errors = [], []
    for competitor, query in SEARCHES.items():
        try:
            found = fetch(competitor, query)
            print(f'{competitor}: {len(found)} relevant headline candidates')
            articles.extend(found)
        except Exception as exc:
            errors.append(f'{competitor}: {type(exc).__name__}: {exc}')
    # Preserve last good dataset when collection fails or filtering produces no matches.
    if not articles:
        print('No matching items: existing data preserved. ' + '; '.join(errors))
        return
    unique = {a['url']: a for a in articles}
    for a in unique.values():
        a['titleKo'], a['translationStatus'] = translate(a['title'])
        a['summary'] = ('제목은 자동 번역되었습니다. ' if a['translationStatus'] == 'machine' else '한국어 번역을 가져오지 못했습니다. ') + '기사 본문과 경쟁사 관련성은 검증되지 않았습니다.'
        time.sleep(0.15)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        'updatedAt': dt.datetime.now(dt.timezone.utc).isoformat(timespec='seconds'),
        'source': 'Google News RSS metadata (unverified); headline machine translation (unofficial)',
        'articles': sorted(unique.values(), key=lambda a: a['publishedAt'], reverse=True),
        'errors': errors,
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Saved {len(unique)} headlines, translated {sum(a["translationStatus"] == "machine" for a in unique.values())}, feed errors {len(errors)}')

if __name__ == '__main__':
    main()
