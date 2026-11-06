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
    """Best-effort Korean headline translation with two no-key endpoints.

    Neither endpoint has an availability guarantee; retain English on failure.
    """
    # Provider 1: unofficial Google Translate endpoint (already used by this project).
    try:
        url = 'https://translate.googleapis.com/translate_a/single?' + urllib.parse.urlencode({
            'client': 'gtx', 'sl': 'en', 'tl': 'ko', 'dt': 't', 'q': title})
        result = json.loads(get(url).decode('utf-8'))
        korean = ''.join(part[0] for part in result[0] if part and isinstance(part[0], str)).strip()
        if korean and korean.casefold() != title.casefold():
            return korean, 'machine_google'
  except (OSError, ValueError, IndexError, TypeError, KeyError) as e:
    print(f"Google translation failed: {type(e).__name__}: {e}")

    # Provider 2: MyMemory public translation endpoint; subject to free rate limits.
    try:
        url = 'https://api.mymemory.translated.net/get?' + urllib.parse.urlencode({
            'q': title[:450], 'langpair': 'en|ko'})
        result = json.loads(get(url).decode('utf-8'))
        korean = (result.get('responseData') or {}).get('translatedText', '').strip()
        if (result.get('responseStatus') == 200 and korean
                and korean.casefold() != title.casefold()
                and 'MYMEMORY WARNING' not in korean.upper()):
            return korean, 'machine_mymemory'
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as e:
    print(f"MyMemory translation failed: {type(e).__name__}: {e}")
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
