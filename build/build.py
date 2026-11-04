"""Build the site's data: TimeScore lists and races for each source.

Reads the daily files in data/imdb and data/tmdb, scores every movie with
TimeScore at four half-lives (a day, a week, a month and a year), and writes
site/data/movies.json with:

- the top movies at each half-life as of the latest day, with how far each
  moved since the day before, and the weekly trending list (each movie's
  Week score divided by its Month score);
- race data: the daily values of every movie that made a top 10 at any
  half-life on any day, for the page to animate;
- when it was built and the latest day of each source, so the page can show
  whether the daily update is running.
"""

import datetime
import glob
import heapq
import json
import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'collect'))
sys.path.insert(0, os.path.dirname(__file__))

from timescore import EMPTY, add_event, score_at  # noqa: E402
import posters  # noqa: E402

HALF_LIVES = [('Day', 1), ('Week', 7), ('Month', 30.44), ('Year', 365.25)]
LIST_SIZE = 20
RACE_SIZE = 10

# Weekly trending: a movie's Week score divided by its Month score, divided
# again by what that ratio would be for a movie with the same activity every
# day, so 1.0 is a movie's usual pace and 2.0 twice its usual pace. Only the
# TRENDING_POOL movies with the highest Week scores qualify, so a movie with
# one recent like can't top the list.
TRENDING = 'Weekly trending'
TRENDING_POOL = 100


def steady(half_life, days):
    """The score of one event a day for this many days, on the last day."""
    fade = 2 ** (-1 / half_life)
    return (1 - fade ** days) / (1 - fade)

SOURCES = {
    'imdb': {
        'name': 'New IMDb ratings',
        'about': 'Movies ranked by the ratings people gave them on IMDb, each day\'s new '
                 'ratings counting as one event worth that many ratings.',
        'unit': 'ratings',
        'link': 'https://www.imdb.com/title/{id}/',
        'credit': 'Information courtesy of IMDb (https://www.imdb.com). Used with permission.',
    },
    'tmdb': {
        'name': 'TMDB popularity',
        'about': 'Movies ranked by The Movie Database\'s daily popularity score, each day\'s '
                 'score counting as one event.',
        'unit': 'popularity',
        'link': 'https://www.themoviedb.org/movie/{id}',
        'credit': 'This product uses the TMDB API but is not endorsed or certified by TMDB.',
    },
}


def read_days(source):
    """Each day's events for a source: [(date, {key: (value, title)})], oldest first."""
    days = []
    for path in sorted(glob.glob(os.path.join('data', source, '*.tsv'))):
        date = datetime.date.fromisoformat(os.path.basename(path)[:-4])
        events = {}
        with open(path, encoding='utf-8') as f:
            lines = [line for line in f if not line.startswith('#')]
        for line in lines[1:]:
            parts = line.rstrip('\n').split('\t')
            if source == 'imdb':
                tconst, value, title, year = parts
                events[f'imdb:{tconst}'] = (float(value), f'{title} ({year})' if year else title)
            else:
                tmdb_id, value, title = parts
                events[f'tmdb:{tmdb_id}'] = (float(value), title)
        days.append((date, events))
    return days


def top(scores, n):
    """The n keys with the highest stored scores, highest first."""
    return heapq.nlargest(n, scores, key=scores.get)


def build_source(source, days):
    start = days[0][0]
    titles = {}
    lists, racers = {}, set()
    final, previous = {}, {}   # each half-life's stored scores on the last two days
    for label, half_life in HALF_LIVES:
        scores, before = {}, []
        previous[label] = {}
        for i, (date, events) in enumerate(days):
            day = (date - start).days
            for key, (value, title) in events.items():
                titles[key] = title
                if value > 0:
                    scores[key] = add_event(scores.get(key, EMPTY), value, day, half_life)
            racers.update(top(scores, RACE_SIZE))
            if i == len(days) - 2:
                before = top(scores, LIST_SIZE * 2)
                previous[label] = dict(scores)
        final[label] = scores
        last = (days[-1][0] - start).days
        lists[label] = [{
            'key': key,
            'score': round(score_at(scores[key], last, half_life), 2),
            'previous': before.index(key) + 1 if key in before else None,
        } for key in top(scores, LIST_SIZE)]

    last = (days[-1][0] - start).days
    now = trending(final['Week'], final['Month'], last)
    before = [key for key, _ in trending(previous['Week'], previous['Month'], last - 1)]
    lists[TRENDING] = [{
        'key': key,
        'score': round(ratio, 2),
        'previous': before.index(key) + 1 if key in before else None,
    } for key, ratio in now[:LIST_SIZE]]
    return start, titles, lists, racers


def trending(week, month, day):
    """The pool of top movies by Week score, ordered by Week score divided by
    Month score (1.0 being a steady pace): [(key, ratio)], highest first."""
    pool = top(week, TRENDING_POOL)
    usual = steady(7, day + 1) / steady(30.44, day + 1)
    ratios = [(key, score_at(week[key], day, 7) / score_at(month[key], day, 30.44) / usual)
              for key in pool]
    return sorted(ratios, key=lambda item: -item[1])


def main():
    out = {
        'generated': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
        'halfLives': [{'label': label, 'days': days} for label, days in HALF_LIVES],
        'trending': TRENDING,
        'sources': {},
    }
    built = {}
    for source in SOURCES:
        days = read_days(source)
        if days:
            built[source] = (days, *build_source(source, days))

    keys = set()
    for days, start, titles, lists, racers in built.values():
        keys |= racers | {item['key'] for items in lists.values() for item in items}
    found = posters.ensure(sorted(keys))

    def movie(key, titles):
        row = found.get(key)
        ident = key.split(':', 1)[1]
        source = key.split(':', 1)[0]
        # TMDB's export titles are original-language; prefer TMDB's English title.
        title = titles[key]
        if source == 'tmdb' and row and row.get('title'):
            title = row['title'] + (f' ({row["year"]})' if row.get('year') else '')
        return {'title': title, 'poster': posters.url(row), 'link': SOURCES[source]['link'].format(id=ident)}

    for source, info in SOURCES.items():
        entry = {**info, 'collected': 0, 'start': None, 'last': None}
        if source in built:
            days, start, titles, lists, racers = built[source]
            entry.update({
                'collected': len(days),
                'start': start.isoformat(),
                'last': days[-1][0].isoformat(),
                'movies': {key: movie(key, titles) for key in
                           racers | {item['key'] for items in lists.values() for item in items}},
                'lists': lists,
                'race': {key: [[(date - start).days, events[key][0]] for date, events in days if key in events]
                         for key in sorted(racers)},
            })
        out['sources'][source] = entry

    os.makedirs('site/data', exist_ok=True)
    with open('site/data/movies.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    for source, entry in out['sources'].items():
        print(f"{source}: {entry['collected']} day(s), {entry['start']} to {entry['last']}")


if __name__ == '__main__':
    main()
