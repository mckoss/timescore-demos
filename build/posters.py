"""Movie posters (and English titles) from the TMDB API, cached in
data/posters.tsv so each movie is looked up once.

Needs a TMDB API Read Access Token in the TMDB_TOKEN environment variable
(a free TMDB account gives one). Without it, movies have no posters.

This product uses the TMDB API but is not endorsed or certified by TMDB.
"""

import csv
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

API = 'https://api.themoviedb.org/3'
IMAGES = 'https://image.tmdb.org/t/p/'
CACHE = 'data/posters.tsv'
FIELDS = ['key', 'tmdb_id', 'title', 'year', 'poster_path', 'checked']
RETRY_DAYS = 30   # look again for a movie that had no poster this long ago

csv.field_size_limit(sys.maxsize)


def load(path=CACHE):
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8', newline='') as f:
        return {row['key']: row for row in csv.DictReader(f, delimiter='\t')}


def save(posters, path=CACHE):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, FIELDS, delimiter='\t', lineterminator='\n')
        writer.writeheader()
        for key in sorted(posters):
            writer.writerow(posters[key])


def get(path, token):
    request = urllib.request.Request(f'{API}{path}', headers={
        'Authorization': f'Bearer {token}', 'Accept': 'application/json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def lookup(key, token):
    """A cache row for 'imdb:tt…' or 'tmdb:123'."""
    source, ident = key.split(':', 1)
    if source == 'imdb':
        found = get(f'/find/{ident}?external_source=imdb_id', token) or {}
        movie = (found.get('movie_results') or [None])[0]
    else:
        movie = get(f'/movie/{ident}', token)
    today = datetime.date.today().isoformat()
    if not movie:
        return {'key': key, 'tmdb_id': '', 'title': '', 'year': '', 'poster_path': '', 'checked': today}
    return {
        'key': key,
        'tmdb_id': str(movie.get('id', '')),
        'title': ' '.join((movie.get('title') or '').split()),
        'year': (movie.get('release_date') or '')[:4],
        'poster_path': movie.get('poster_path') or '',
        'checked': today,
    }


def ensure(keys, token=None):
    """The cache, after looking up any of keys it lacks (when there's a token)."""
    posters = load()
    token = token or os.environ.get('TMDB_TOKEN')
    if not token:
        print('No TMDB_TOKEN: skipping poster lookups.')
        return posters
    stale = (datetime.date.today() - datetime.timedelta(days=RETRY_DAYS)).isoformat()
    missing = [key for key in keys
               if key not in posters or (not posters[key]['poster_path'] and posters[key]['checked'] < stale)]
    for key in missing:
        try:
            posters[key] = lookup(key, token)
        except (urllib.error.URLError, TimeoutError) as error:
            print(f'Poster lookup for {key} failed: {error}')
    if missing:
        save(posters)
        print(f'Looked up {len(missing)} poster(s).')
    return posters


def url(row, size='w185'):
    return f'{IMAGES}{size}{row["poster_path"]}' if row and row.get('poster_path') else None
