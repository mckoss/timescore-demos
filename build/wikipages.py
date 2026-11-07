"""Wikipedia articles' display titles, short descriptions and free images,
cached in data/wikipedia-pages.tsv so each article is looked up once.

Only freely licensed images are used (Wikimedia Commons and free files on
English Wikipedia), never the non-free posters and logos English Wikipedia
shows under fair use. Each image keeps its author and license, which the
site shows with it. No token is needed.
"""

import datetime
import html
import os
import re
import sys
import urllib.error
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'collect'))
from wikipedia import get_json  # noqa: E402

API = 'https://en.wikipedia.org/w/api.php'
CACHE = 'data/wikipedia-pages.tsv'
FIELDS = ['key', 'title', 'description', 'thumbnail', 'file', 'artist', 'license', 'file_page', 'checked']
BATCH = 50          # titles per API request (the API's limit)
THUMB_SIZE = 185    # pixels, like the movie posters
RETRY_DAYS = 30     # look again for an article that had no image this long ago


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
    data = query(titles='|'.join(names), redirects='1', prop='pageimages|description',
                 piprop='thumbnail|name', pithumbsize=str(THUMB_SIZE), pilicense='free')
    result = data.get('query', {})
    # Follow the API's normalizing ("a" → "A") and redirects back to our keys.
    origin = dict(names)
    for step in ('normalized', 'redirects'):
        for change in result.get(step, []):
            if change['from'] in origin:
                origin[change['to']] = origin[change['from']]
    today = datetime.date.today().isoformat()
    rows = {key: {'key': key, 'title': article_name(key).replace('_', ' '), 'checked': today} for key in keys}
    for page in result.get('pages', []):
        key = origin.get(page.get('title'))
        if not key:
            continue
        row = rows[key]
        row['title'] = page['title']
        row['description'] = page.get('description', '')
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


def ensure(keys):
    """The cache, after looking up any of keys it lacks."""
    pages = load()
    stale = (datetime.date.today() - datetime.timedelta(days=RETRY_DAYS)).isoformat()
    missing = [key for key in keys
               if key not in pages or (not pages[key].get('thumbnail') and pages[key]['checked'] < stale)]
    looked_up = 0
    for i in range(0, len(missing), BATCH):
        try:
            pages.update(lookup(missing[i:i + BATCH]))
            looked_up += len(missing[i:i + BATCH])
        except (urllib.error.URLError, TimeoutError) as error:
            print(f'Wikipedia lookup failed: {error}')
            break
    if looked_up:
        save(pages)
        print(f'Looked up {looked_up} Wikipedia article(s).')
    return pages


def link(key):
    return 'https://en.wikipedia.org/wiki/' + urllib.parse.quote(article_name(key), safe="_(),'!-.:/")
