"""Daily IMDb collector: the movies that got the most new votes since the
last snapshot.

IMDb publishes only the current vote count for each title, so new votes are
the difference between today's file and the previous snapshot. The full
snapshot is kept in the workflow's cache (STATE), not in the repository:
IMDb's terms don't allow republishing its data. The repository keeps only a
small daily ranking, data/imdb/YYYY-MM-DD.tsv: the TOP movies by new votes.

Information courtesy of IMDb (https://www.imdb.com). Used with permission.
IMDb data is for personal and non-commercial use only.
"""

import argparse
import csv
import datetime
import email.utils
import gzip
import io
import os
import sys
import urllib.request

RATINGS = 'https://datasets.imdbws.com/title.ratings.tsv.gz'
BASICS = 'https://datasets.imdbws.com/title.basics.tsv.gz'
USER_AGENT = 'timescore-demos (https://github.com/mckoss/timescore-demos)'
TOP = 500          # movies kept per day
MIN_VOTES = 1000   # movies with fewer votes in all are left out

csv.field_size_limit(sys.maxsize)


def fetch(url):
    """The file at url, and the date it was last modified (UTC)."""
    request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(request, timeout=600) as response:
        modified = email.utils.parsedate_to_datetime(response.headers['Last-Modified'])
        return response.read(), modified.astimezone(datetime.timezone.utc).date()


def rows(data):
    """The rows of a gzipped IMDb TSV file, as dicts."""
    text = io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(data)), encoding='utf-8')
    return csv.DictReader(text, delimiter='\t', quoting=csv.QUOTE_NONE)


def read_state(path):
    """The previous snapshot: its date, and votes for each movie."""
    if not os.path.exists(path):
        return None, {}
    with gzip.open(path, 'rt', encoding='utf-8') as f:
        date = datetime.date.fromisoformat(f.readline().strip())
        votes = {}
        for line in f:
            tconst, count = line.rstrip('\n').split('\t')
            votes[tconst] = int(count)
    return date, votes


def write_state(path, date, votes):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with gzip.open(path, 'wt', encoding='utf-8') as f:
        f.write(date.isoformat() + '\n')
        for tconst, count in votes.items():
            f.write(f'{tconst}\t{count}\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--state', default='.cache/imdb-state.tsv.gz')
    parser.add_argument('--out', default='data/imdb')
    args = parser.parse_args()

    ratings, date = fetch(RATINGS)
    previous_date, previous = read_state(args.state)
    if previous_date is not None and date <= previous_date:
        print(f'IMDb ratings dated {date} were already collected; nothing to do.')
        return

    basics, _ = fetch(BASICS)
    movies = {}
    for row in rows(basics):
        if row['titleType'] == 'movie':
            year = row['startYear'] if row['startYear'] != r'\N' else ''
            movies[row['tconst']] = (row['primaryTitle'], year)
    del basics

    votes = {}
    for row in rows(ratings):
        if row['tconst'] in movies:
            votes[row['tconst']] = int(row['numVotes'])
    print(f'IMDb ratings dated {date}: {len(votes)} movies with votes.')

    if previous_date is None:
        print('No previous snapshot; saved this one as the baseline.')
    else:
        # A movie new to the file has no baseline, so it starts tomorrow.
        new = [(count - previous[tconst], tconst) for tconst, count in votes.items()
               if tconst in previous and count >= MIN_VOTES and count > previous[tconst]]
        new.sort(reverse=True)
        os.makedirs(args.out, exist_ok=True)
        path = os.path.join(args.out, f'{date.isoformat()}.tsv')
        with open(path, 'w', encoding='utf-8', newline='') as f:
            f.write(f'# New IMDb votes from {previous_date} to {date}. '
                    'Information courtesy of IMDb (https://www.imdb.com). Used with permission.\n')
            f.write('tconst\tnew_votes\ttitle\tyear\n')
            for count, tconst in new[:TOP]:
                title, year = movies[tconst]
                f.write(f'{tconst}\t{count}\t{title}\t{year}\n')
        print(f'Wrote {path}: top {min(TOP, len(new))} of {len(new)} movies with new votes.')

    write_state(args.state, date, votes)


if __name__ == '__main__':
    main()
