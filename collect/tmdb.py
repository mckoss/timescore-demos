"""Daily TMDB collector: the most popular movies on The Movie Database.

TMDB publishes a daily export of every movie with its popularity score for
that day, and keeps the files for about three months. This keeps the TOP
movies of each day in data/tmdb/YYYY-MM-DD.tsv, collecting every day that is
still available and not yet collected.

This product uses the TMDB API but is not endorsed or certified by TMDB.
"""

import argparse
import datetime
import gzip
import io
import json
import os
import urllib.error
import urllib.request

EXPORT = 'https://files.tmdb.org/p/exports/movie_ids_{d:%m}_{d:%d}_{d:%Y}.json.gz'
USER_AGENT = 'timescore-demos (https://github.com/mckoss/timescore-demos)'
TOP = 500   # movies kept per day


def fetch(url):
    """The file at url, or None if there isn't one (yet, or any more)."""
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=600) as response:
            return response.read()
    except urllib.error.HTTPError as error:
        if error.code in (403, 404):
            return None
        raise


def collect(day, out):
    path = os.path.join(out, f'{day.isoformat()}.tsv')
    if os.path.exists(path):
        return False
    data = fetch(EXPORT.format(d=day))
    if data is None:
        return False
    movies = []
    with gzip.open(io.BytesIO(data), 'rt', encoding='utf-8') as f:
        for line in f:
            movie = json.loads(line)
            if not movie.get('adult') and not movie.get('video'):
                movies.append((movie['popularity'], movie['id'], movie['original_title']))
    movies.sort(reverse=True)
    os.makedirs(out, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(f'# TMDB popularity on {day}. '
                'This product uses the TMDB API but is not endorsed or certified by TMDB.\n')
        f.write('tmdb_id\tpopularity\ttitle\n')
        for popularity, tmdb_id, title in movies[:TOP]:
            title = ' '.join(title.split())  # no tabs or newlines
            f.write(f'{tmdb_id}\t{popularity:.3f}\t{title}\n')
    print(f'Wrote {path}: top {min(TOP, len(movies))} of {len(movies)} movies.')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', default='data/tmdb')
    parser.add_argument('--days', type=int, default=100,
                        help='how many days back to look for files not yet collected')
    args = parser.parse_args()
    today = datetime.datetime.now(datetime.timezone.utc).date()
    collected = sum(collect(today - datetime.timedelta(days=n), args.out)
                    for n in range(args.days, -1, -1))
    print(f'Collected {collected} new day(s) of TMDB data.')


if __name__ == '__main__':
    main()
