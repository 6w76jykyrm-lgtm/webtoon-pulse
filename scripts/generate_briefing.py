#!/usr/bin/env python3
"""Generate a source-grounded Korean market briefing from Google News RSS metadata."""
import datetime as dt
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'data' / 'news.json'
OUTPUT = ROOT / 'data' / 'briefing.json'
MODEL = os.getenv('GEMINI_MODEL', 'gemini-2.5-flash-lite')


def main():
    key = os.getenv('GEMINI_API_KEY', '').strip()
    if not key:
        raise RuntimeError('GEMINI_API_KEY GitHub Actions secret is missing')
    source = json.loads(SOURCE.read_text(encoding='utf-8'))
    articles = [a for a in source.get('articles', []) if a.get('title') and a.get('url')][:20]
    if not articles:
        raise RuntimeError('No source articles found; briefing was not overwritten')
    compact = [
        {'id': a['id'], 'title': a['title'], 'titleKo': a.get('titleKo', ''),
         'publishedAt': a.get('publishedAt', ''), 'competitor': a.get('competitor', ''),
         'source': a.get('source', '')}
        for a in articles if a.get('id')
    ]
    prompt = (
        '너는 북미 웹툰 시장 리서치 분석가다. 아래 자료는 검증되지 않은 Google News RSS 제목 메타데이터다. '
        '기사 본문을 읽었다고 주장하거나 제목만으로 매출, 성과, 인과관계를 단정하지 마라. '
        '자료에 없는 사실은 절대 추가하지 마라. 한국어로 간결하게 작성하라. '
        '제목에 나타난 관찰과 해석/CRM 실험 가설을 명확히 구분하라. '
        'JSON 객체만 출력하며 다음 필드를 포함하라: '
        'headline(문자열), signals(최대 3개 배열, 각 원소는 title, observation, implication, '
        'crmHypothesis, sourceIds 배열), limitations(문자열). '
        'sourceIds는 입력 기사 id에서만 선택하라. 충분한 근거가 없으면 signals를 빈 배열로 둬라.\n'
        'RSS 기사 목록:\n' + json.dumps(compact, ensure_ascii=False)
    )
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent'
    body = {'contents': [{'parts': [{'text': prompt}]}],
            'generationConfig': {'responseMimeType': 'application/json', 'temperature': 0.2}}
    request = urllib.request.Request(
        url, data=json.dumps(body).encode('utf-8'),
        headers={'Content-Type': 'application/json', 'x-goog-api-key': key}, method='POST')
    try:
        with urllib.request.urlopen(request, timeout=75) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        # Do not print request headers or credentials.
        raise RuntimeError(f'Gemini API HTTP {exc.code}; check model access, quota and API key') from exc
    parts = result.get('candidates', [{}])[0].get('content', {}).get('parts', [])
    raw = ''.join(part.get('text', '') for part in parts)
    if not raw:
        raise RuntimeError('Gemini returned no text; briefing was not overwritten')
    briefing = json.loads(raw)
    if not isinstance(briefing, dict) or not isinstance(briefing.get('signals'), list):
        raise RuntimeError('Gemini response does not match expected format')
    allowed = {a['id']: a for a in articles if a.get('id')}
    cleaned = []
    for signal in briefing['signals'][:3]:
        if not isinstance(signal, dict):
            continue
        ids = [i for i in signal.get('sourceIds', []) if isinstance(i, str) and i in allowed]
        if not ids:
            continue
        cleaned.append({
            'title': str(signal.get('title', '')),
            'observation': str(signal.get('observation', '')),
            'implication': str(signal.get('implication', '')),
            'crmHypothesis': str(signal.get('crmHypothesis', '')),
            'sources': [{'id': i, 'title': allowed[i]['title'], 'url': allowed[i]['url']} for i in ids[:3]],
        })
    payload = {
        'generatedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
        'model': MODEL,
        'headline': str(briefing.get('headline', '북미 웹툰 시장 브리핑')),
        'signals': cleaned,
        'limitations': str(briefing.get('limitations', 'RSS 제목 기반 분석이며 기사 본문은 검증되지 않았습니다.')),
        'sourceUpdatedAt': source.get('updatedAt'),
        'verificationStatus': 'rss_headlines_unverified',
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'Saved {len(cleaned)} briefing signals to {OUTPUT}')


if __name__ == '__main__':
    main()
