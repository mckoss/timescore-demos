"""Wikipedia articles' display titles, short descriptions, free images and
topics, cached in data/wikipedia-pages.tsv so each article is looked up once.

Only freely licensed images are used (Wikimedia Commons and free files on
English Wikipedia), never the non-free posters and logos English Wikipedia
shows under fair use. Each image keeps its author and license, which the
site shows with it.

Topics come from Wikimedia's article topic model (Lift Wing's
outlink-topic-model), which tags an article with any of 64 subjects, and
are grouped into the few the site shows (GROUPS). The model tags what an
article is about, not whether it is about a person, so People comes from
Wikipedia instead: articles in "Living people", and articles whose short
description gives a life's years ("English actor (1940–2026)",
"(born 1989)"), as Wikipedia's style for biographies asks.

No token is needed.
"""

import datetime
import html
import os
import re
import sys
import time
import urllib.error
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'collect'))
from wikipedia import get_json  # noqa: E402

API = 'https://en.wikipedia.org/w/api.php'
TOPIC_MODEL = 'https://api.wikimedia.org/service/lw/inference/v1/models/outlink-topic-model:predict'
CACHE = 'data/wikipedia-pages.tsv'
FIELDS = ['key', 'title', 'description', 'thumbnail', 'file', 'artist', 'license', 'file_page', 'checked',
          'living', 'topics', 'topics_checked']
BATCH = 50          # titles per API request (the API's limit)
THUMB_SIZE = 185    # pixels, like the movie posters
RETRY_DAYS = 30     # look again for an article that had no image this long ago
TOPIC_LOOKUPS = 1000   # topic model requests per run, at most; the rest wait for the next run
TOPIC_PAUSE = 0.2      # seconds between them
TOPIC_BUDGET = 10 * 60   # seconds a run may spend on them

# The topic groups the site shows, each from the model's topics (an article
# can be in several). Places is for articles that are only about a place.
GROUPS = [
    ('people', 'People'),
    ('politics', 'Politics'),
    ('sports', 'Sports'),
    ('entertainment', 'Entertainment'),
    ('science', 'Science & tech'),
    ('business', 'Business'),
    ('history', 'History'),
    ('places', 'Places'),
]
TOPIC_GROUPS = {
    'politics': ('History_and_Society.Politics_and_government',),
    'sports': ('Culture.Sports',),
    'entertainment': ('Culture.Media.Films', 'Culture.Media.Television', 'Culture.Media.Music',
                      'Culture.Media.Video_games', 'Culture.Media.Entertainment', 'Culture.Media.Books',
                      'Culture.Media.Radio', 'Culture.Performing_arts'),
    'science': ('STEM.',),
    'business': ('History_and_Society.Business_and_economics',),
    'history': ('History_and_Society.History', 'History_and_Society.Military_and_warfare'),
}
PLACE_SCORE = 0.8   # how sure the model must be that an article is about a place
LIFE_YEARS = re.compile(r'\((?:born \d{3,4}|c?\.? ?\d{3,4}\s*[–-]\s*\d{2,4})\)')


def load(path=CACHE):
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()
    header = lines[0].split('\t')
    return {row['key']: row for row in (dict(zip(header, line.split('\t'))) for line in lines[1:] if line)}


def save(pages, path=CACHE):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('\t'.join(FIELDS) + '\n')
        for key in sorted(pages):
            f.write('\t'.join(clean(pages[key].get(field, '')) for field in FIELDS) + '\n')


def clean(text):
    """One line of plain text, safe in a TSV cell."""
    return ' '.join(str(text or '').split())


def plain(markup):
    """An author credit from Commons, which is HTML, as plain text."""
    return clean(html.unescape(re.sub(r'<[^>]+>', ' ', markup or '')))


def query(**params):
    params = {'action': 'query', 'format': 'json', 'formatversion': '2', **params}
    return get_json(f'{API}?{urllib.parse.urlencode(params)}') or {}


def article_name(key):
    return key.split(':', 1)[1]


def lookup(keys):
    """Cache rows for up to BATCH 'wikipedia:Article_name' keys."""
    names = {article_name(key).replace('_', ' '): key for key in keys}
    data = query(titles='|'.join(names), redirects='1', prop='pageimages|description|categories',
                 piprop='thumbnail|name', pithumbsize=str(THUMB_SIZE), pilicense='free',
                 clcategories='Category:Living people', cllimit='max')
    result = data.get('query', {})
    # Follow the API's normalizing ("a" → "A") and redirects back to our keys.
    origin = dict(names)
    for step in ('normalized', 'redirects'):
        for change in result.get(step, []):
            if change['from'] in origin:
                origin[change['to']] = origin[change['from']]
    today = datetime.date.today().isoformat()
    rows = {key: {'key': key, 'title': article_name(key).replace('_', ' '), 'checked': today, 'living': '0'}
            for key in keys}
    for page in result.get('pages', []):
        key = origin.get(page.get('title'))
        if not key:
            continue
        row = rows[key]
        row['title'] = page['title']
        row['description'] = page.get('description', '')
        row['living'] = '1' if page.get('categories') else '0'
        if page.get('thumbnail') and page.get('pageimage'):
            row['thumbnail'] = page['thumbnail']['source'].split('?')[0]   # less its tracking query
            row['file'] = page['pageimage']
    credit(rows.values())
    return rows


def credit(rows):
    """Adds each image's author, license and description page."""
    files = {f'File:{row["file"].replace("_", " ")}': row for row in rows if row.get('file')}
    if not files:
        return
    data = query(titles='|'.join(files), prop='imageinfo', iiprop='extmetadata|url',
                 iiextmetadatafilter='Artist|LicenseShortName')
    result = data.get('query', {})
    origin = dict(files)
    for change in result.get('normalized', []):
        if change['from'] in origin:
            origin[change['to']] = origin[change['from']]
    for page in result.get('pages', []):
        row = origin.get(page.get('title'))
        info = (page.get('imageinfo') or [{}])[0]
        if not row:
            continue
        meta = info.get('extmetadata', {})
        row['artist'] = plain(meta.get('Artist', {}).get('value'))
        row['license'] = plain(meta.get('LicenseShortName', {}).get('value'))
        row['file_page'] = info.get('descriptionurl', '')


def ensure(keys, topic_keys=()):
    """The cache, after looking up any of keys it lacks, and the topics of
    any of topic_keys (which also get looked up) it lacks."""
    pages = load()
    keys = list(dict.fromkeys([*keys, *topic_keys]))
    stale = (datetime.date.today() - datetime.timedelta(days=RETRY_DAYS)).isoformat()
    missing = [key for key in keys
               if key not in pages or not pages[key].get('living')
               or (not pages[key].get('thumbnail') and pages[key]['checked'] < stale)]
    looked_up = 0
    for i in range(0, len(missing), BATCH):
        try:
            for key, row in lookup(missing[i:i + BATCH]).items():
                pages[key] = {**pages.get(key, {}), **row}
            looked_up += len(missing[i:i + BATCH])
        except (urllib.error.URLError, TimeoutError) as error:
            print(f'Wikipedia lookup failed: {error}')
            break
    if looked_up:
        save(pages)
        print(f'Looked up {looked_up} Wikipedia article(s).')
    tagged = tag_topics(pages, [key for key in topic_keys if key in pages and not pages[key].get('topics_checked')])
    if tagged:
        save(pages)
        print(f'Looked up the topics of {tagged} Wikipedia article(s).')
    return pages


def topics_of(title):
    """The topic model's topics for an article: 'Topic:score;…' (those it is
    at least 50% sure of), or None when it has no answer."""
    try:
        data = get_json(TOPIC_MODEL, missing_tries=1, body={'page_title': title.replace(' ', '_'), 'lang': 'en'})
    except urllib.error.HTTPError as error:
        if 400 <= error.code < 500 and error.code != 429:
            return ''   # the model can't score this page (a redirect, a new page): no topics
        raise
    if data is None:
        return ''
    results = data.get('prediction', {}).get('results', [])
    return ';'.join(f'{r["topic"]}:{r["score"]:.2f}' for r in results)


def tag_topics(pages, keys, limit=TOPIC_LOOKUPS):
    """Adds topics to up to limit of keys' rows; how many it added."""
    today = datetime.date.today().isoformat()
    began = time.monotonic()
    tagged = 0
    for key in keys[:limit]:
        if time.monotonic() - began > TOPIC_BUDGET:
            break
        try:
            topics = topics_of(pages[key].get('title') or article_name(key))
        except (urllib.error.URLError, TimeoutError) as error:
            print(f'Topic lookup failed: {error}')
            break
        pages[key]['topics'] = topics
        pages[key]['topics_checked'] = today
        tagged += 1
        time.sleep(TOPIC_PAUSE)
    if len(keys) > tagged:
        print(f'{len(keys) - tagged} article(s) wait for the next run for their topics.')
    return tagged


def parse_topics(text):
    """{topic: score} from a cache row's topics."""
    out = {}
    for part in (text or '').split(';'):
        if ':' in part:
            topic, score = part.rsplit(':', 1)
            out[topic] = float(score)
    return out


def is_person(row):
    if row.get('living') == '1' or LIFE_YEARS.search(row.get('description') or ''):
        return True
    return 'Culture.Biography.Biography*' in parse_topics(row.get('topics'))


def groups_of(row):
    """The ids of the GROUPS an article is in."""
    if not row:
        return set()
    topics = parse_topics(row.get('topics'))
    groups = {group for group, prefixes in TOPIC_GROUPS.items()
              if any(topic.startswith(prefix) for topic in topics for prefix in prefixes)}
    # The model's general Media tag counts as Entertainment (Patrick Stewart has
    # only that one), unless the article is about science or technology
    # (Microsoft 365 is Media and STEM).
    if 'Culture.Media.Media*' in topics and 'science' not in groups:
        groups.add('entertainment')
    person = is_person(row)
    if person:
        groups.add('people')
    elif topics and all(topic.startswith('Geography.') for topic in topics) \
            and max(topics.values()) >= PLACE_SCORE:
        groups.add('places')
    return groups


def link(key):
    return 'https://en.wikipedia.org/wiki/' + urllib.parse.quote(article_name(key), safe="_(),'!-.:/")
