"""Topics for every Wikipedia article in the data, cached in
data/wikipedia-topics.tsv, so the site can rank each topic's articles.

Topics come from Wikimedia's article topic model (Lift Wing's
outlink-topic-model), which tags an article with any of 64 subjects, and
are grouped into the few the site shows (GROUPS). The model tags what an
article is about, not whether it is about a person, so People comes from
Wikipedia instead: articles in "Living people", and articles whose short
description gives a life's years ("English actor (1940–2026)",
"(born 1989)"), as Wikipedia's style for biographies asks.

Only the articles that can make a topic's list get tagged: ensure() walks
each half-life's ranking from the top and tags articles until every topic
has its list's worth of tagged articles above the first untagged one, so
nothing further down could make a list (going no deeper than DEPTH). Each
article is tagged once, with at most WORKERS requests at a time as
Wikimedia asks, for up to BUDGET seconds a run. No token is needed.
"""

import concurrent.futures
import datetime
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
CACHE = 'data/wikipedia-topics.tsv'
FIELDS = ['key', 'person', 'topics', 'checked']
BATCH = 50          # titles per Wikipedia API request (the API's limit)
WORKERS = 3         # topic model requests at a time (Wikimedia asks for 3 or fewer)
BUDGET = 10 * 60    # seconds a run may spend tagging; the rest waits for the next run
DEPTH = 5000        # how far down each ranking to look for a topic's articles

# The topic groups the site shows, each from the model's topics (an article
# can be in several). Places is for articles that are only about a place.
GROUPS = [
    ('people', 'People'),
    ('politics', 'Politics'),
    ('sports', 'Sports'),
    ('entertainment', 'Entertainment'),
    ('science', 'Science & tech'),
    ('business', 'Business'),
    ('history', 'History & military'),
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


def save(rows, path=CACHE):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('\t'.join(FIELDS) + '\n')
        for key in sorted(rows):
            f.write('\t'.join(' '.join(str(rows[key].get(field) or '').split()) for field in FIELDS) + '\n')


def article_name(key):
    return key.split(':', 1)[1]


def people(keys):
    """{key: (title, is a person)} for up to BATCH keys, from Wikipedia: the
    article's title (after redirects), and whether it's in "Living people"
    or its short description gives a life's years."""
    names = {article_name(key).replace('_', ' '): key for key in keys}
    params = {'action': 'query', 'format': 'json', 'formatversion': '2', 'titles': '|'.join(names),
              'redirects': '1', 'prop': 'description|categories', 'clcategories': 'Category:Living people',
              'cllimit': 'max'}
    result = (get_json(f'{API}?{urllib.parse.urlencode(params)}') or {}).get('query', {})
    origin = dict(names)
    for step in ('normalized', 'redirects'):
        for change in result.get(step, []):
            if change['from'] in origin:
                origin[change['to']] = origin[change['from']]
    out = {key: (article_name(key).replace('_', ' '), False) for key in keys}
    for page in result.get('pages', []):
        key = origin.get(page.get('title'))
        if key:
            person = bool(page.get('categories')) or bool(LIFE_YEARS.search(page.get('description') or ''))
            out[key] = (page['title'], person)
    return out


def topics_of(title):
    """The topic model's topics for an article: 'Topic:score;…' (those it is
    at least 50% sure of), or '' when it has no answer."""
    try:
        data = get_json(TOPIC_MODEL, missing_tries=1, body={'page_title': title.replace(' ', '_'), 'lang': 'en'})
    except urllib.error.HTTPError as error:
        if 400 <= error.code < 500 and error.code != 429:
            return ''   # the model can't score this page (a new page, a redirect)
        raise
    results = (data or {}).get('prediction', {}).get('results', [])
    return ';'.join(f'{r["topic"]}:{r["score"]:.2f}' for r in results)


def needed(rankings, rows, list_size, depth=DEPTH):
    """The untagged keys that could still make a topic's list, most-read
    first: in each ranking (keys, highest first), those above the point where
    every topic has list_size tagged articles."""
    need = {}
    for ranking in rankings:
        counts = dict.fromkeys((group for group, _ in GROUPS), 0)
        for rank, key in enumerate(ranking[:depth]):
            if min(counts.values()) >= list_size:
                break
            if key in rows:
                for group in groups_of(rows[key]):
                    counts[group] += 1
            elif rank < need.get(key, depth):
                need[key] = rank
    return sorted(need, key=need.get)


def ensure(rankings, list_size, budget=BUDGET):
    """The cache, after tagging the articles that could make a topic's list
    (see needed), for up to budget seconds."""
    rows = load()
    began = time.monotonic()
    today = datetime.date.today().isoformat()
    tagged = 0
    left = needed(rankings, rows, list_size)
    with concurrent.futures.ThreadPoolExecutor(WORKERS) as pool:
        while left and time.monotonic() - began < budget:
            batch = left[:BATCH]
            try:
                found = people(batch)
                topics = list(pool.map(lambda key: topics_of(found[key][0]), batch))
            except (urllib.error.URLError, TimeoutError) as error:
                print(f'Topic lookup failed: {error}')
                break
            for key, text in zip(batch, topics):
                rows[key] = {'key': key, 'person': '1' if found[key][1] else '0', 'topics': text, 'checked': today}
            tagged += len(batch)
            left = needed(rankings, rows, list_size)   # tagging may settle some topics' lists
    if tagged:
        save(rows)
    print(f'Tagged the topics of {tagged} Wikipedia article(s)'
          + (f'; {len(left)} wait for later runs.' if left else '; every topic list is settled.'))
    return rows


def parse_topics(text):
    """{topic: score} from a cache row's topics."""
    out = {}
    for part in (text or '').split(';'):
        if ':' in part:
            topic, score = part.rsplit(':', 1)
            out[topic] = float(score)
    return out


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
    if row.get('person') == '1' or 'Culture.Biography.Biography*' in topics:
        groups.add('people')
    elif topics and all(topic.startswith('Geography.') for topic in topics) \
            and max(topics.values()) >= PLACE_SCORE:
        groups.add('places')
    return groups
