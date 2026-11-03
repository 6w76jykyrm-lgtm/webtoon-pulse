                                 r'financial results|stock|shares|nasdaq|analyst|'
                                 r'investor|price target|EPS|revenue|profit|loss)\b', re.I)),
    ('콘텐츠·IP', re.compile(r'\b(series|episode|chapter|adaptation|anime|'
                            r'new title|originals|creator|artist|comic|manhwa|manga)\b', re.I)),
]


def get(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 (WEBTOON Pulse research)'})
    with urllib.request.urlopen(request, timeout=18) as response:
        return response.read(2_000_000)


def translate(title):
    """Best-effort unofficial machine translation; fall back to original title."""
    try:
        url = 'https://translate.googleapis.com/translate_a/single?' + urllib.parse.urlencode({
            'client': 'gtx', 'sl': 'auto', 'tl': 'ko', 'dt': 't', 'q': title})
        result = json.loads(get(url).decode('utf-8'))
        ko = ''.join(part[0] for part in result[0] if part and isinstance(part[0], str)).strip()
        if ko and ko.casefold() != title.casefold():
            return ko, 'machine'
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
    if competitor in UNRELATED and UNRELATED[competitor].search(headline):
        return False
    # Ambiguous names (Tapas, Manta) need explicit comics/platform context.
    if competitor in ('tapas', 'manta'):
        return bool(BRAND_CONTEXT[competitor].search(headline) or STRONG_CONTEXT.search(headline))
    return bool(BRAND_CONTEXT[competitor].search(headline) or
                (STRONG_CONTEXT.search(headline) and WEAK_CONTEXT.search(headline)))


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
            'competitor': competitor,
            'type': category,
            'category': category,
            'title': title,
            'publishedAt': published,
            'url': link,
            'source': source,
            'verificationStatus': 'unverified',
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
        print('No matching items; existing dataset preserved. ' + '; '.join(errors))
        return

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
