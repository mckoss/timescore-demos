"""Build the site's data: TimeScore lists and races for each source.

Reads the daily files in data/imdb, data/tmdb and data/wikipedia, scores
every movie or article with TimeScore at four half-lives (a day, a week, a
month and a year), and writes site/data/movies.json with:

- the top items at each half-life as of the latest day, with how far each
  moved since the day before, and the weekly trending list (each item's
  Week score divided by its Month score);
- for Wikipedia, the same top lists for each topic (People, Politics,
  Sports and so on: wikitopics.GROUPS), ranked among every article in the
  data that has been tagged with its topics;
- for each item shown: its title, image, link and (for Wikipedia) its short
  description and the image's author and license;
- each shown item's daily values (series), for the page to score at any
  half-life: for the race (racers: every item that made a top 10 at any
  half-life on any day) and for the history chart of any item in a list;
- when it was built and the latest day of each source, so the page can show
  whether the daily update is running.

For Wikipedia it also writes every article's daily values, in SERIES_SHARDS
files under site/data/wikipedia/ (series-NN.json, the shard picked by
shard_of), and index.json, every article from most-read down. The page
falls back to these when Wikimedia's own API doesn't answer. They're
rebuilt on each deploy and not committed (.gitignore).

It also writes site/data/race.json, a small file for the bar chart race in
the TimeScore post on mckoss.com: each week's Wikipedia views of a few
articles picked from the latest data (write_race).
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
import wikipages  # noqa: E402
import wikitopics  # noqa: E402

HALF_LIVES = [('Day', 1), ('Week', 7), ('Month', 30.44), ('Year', 365.25)]
LIST_SIZE = 23     # each list: the 20 the page shows, and 3 fading out below
RACE_SIZE = 10
TOPIC_MIN = 5      # a topic needs this many articles in every half-life's list to be shown
SHOWN = LIST_SIZE  # how many of each list the page shows

# Weekly trending: a movie's Week score divided by its Month score, divided
# again by what that ratio would be for a movie with the same activity every
# day, so 1.0 is a movie's usual pace and 2.0 twice its usual pace. Only the
# TRENDING_POOL movies with the highest Week scores qualify, so a movie with
# one recent like can't top the list.
TRENDING = 'Weekly trending'
TRENDING_POOL = 100
TRENDING_MIN_DAYS = 14   # a source needs this much data for weeks and months to differ


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
        'noun': 'movies',
        'link': 'https://www.imdb.com/title/{id}/',
        'credit': 'Information courtesy of IMDb (https://www.imdb.com). Used with permission.',
    },
    'tmdb': {
        'name': 'TMDB popularity',
        'about': 'Movies ranked by The Movie Database\'s daily popularity score, each day\'s '
                 'score counting as one event.',
        'unit': 'popularity',
        'noun': 'movies',
        'link': 'https://www.themoviedb.org/movie/{id}',
        'credit': 'This product uses the TMDB API but is not endorsed or certified by TMDB.',
    },
    'wikipedia': {
        'name': 'Wikipedia pageviews',
        'about': 'English Wikipedia articles ranked by how many times they were read, each '
                 'day\'s views counting as one event. Pages that aren\'t articles, and pages '
                 'whose views look automated, are left out.',
        'unit': 'views',
        'noun': 'articles',
        'link': 'https://en.wikipedia.org/wiki/{id}',
        'credit': 'Pageview data from the Wikimedia Foundation (CC0). Images from Wikimedia '
                  'Commons and Wikipedia, under the licenses shown with each.',
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
                ident, value, title = parts
                events[f'{source}:{ident}'] = (float(value), title)
        days.append((date, events))
    return days


def top(scores, n):
    """The n keys with the highest stored scores, highest first."""
    return heapq.nlargest(n, scores, key=scores.get)


def build_source(source, days, pools=None):
    """Each half-life's top list (and the trending list) as of the last day.
    If pools is a dict, it gets each half-life's ranking of every key, with
    scores, on the last day, and of every key on the day before:
    {label: (now, before)}."""
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
                before = (sorted(scores, key=scores.get, reverse=True) if pools is not None
                          else top(scores, LIST_SIZE * 2))
                previous[label] = dict(scores)
        final[label] = scores
        last = (days[-1][0] - start).days
        if pools is not None:
            pools[label] = ([(key, round(score_at(scores[key], last, half_life), 2))
                             for key in sorted(scores, key=scores.get, reverse=True)], before)
        before = before[:LIST_SIZE * 2]
        lists[label] = [{
            'key': key,
            'score': round(score_at(scores[key], last, half_life), 2),
            'previous': before.index(key) + 1 if key in before else None,
        } for key in top(scores, LIST_SIZE)]

    last = (days[-1][0] - start).days
    if len(days) < TRENDING_MIN_DAYS:
        return start, titles, lists, racers
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


def article(key, title, row):
    """A Wikipedia article's entry: its free image (if any) and that image's credit."""
    row = row or {}
    out = {'title': row.get('title') or title, 'image': row.get('thumbnail') or None,
           'link': wikipages.link(key)}
    if row.get('description'):
        out['description'] = row['description']
    if out['image']:
        out['imageCredit'] = ', '.join(part for part in (row.get('artist'), row.get('license')) if part)
        out['imagePage'] = row.get('file_page') or None
    return out


def topic_lists(pools, groups):
    """{group: {half-life: list}} for each topic group with enough articles,
    from the pools build_source filled and each key's set of groups."""
    out = {}
    for group, _ in wikitopics.GROUPS:
        lists = {}
        for label, (now, before) in pools.items():
            mine = [(key, score) for key, score in now if group in groups.get(key, ())][:SHOWN]
            earlier = [key for key in before if group in groups.get(key, ())][:LIST_SIZE * 2]
            lists[label] = [{'key': key, 'score': score,
                             'previous': earlier.index(key) + 1 if key in earlier else None}
                            for key, score in mine]
        if lists and all(len(items) >= TOPIC_MIN for items in lists.values()):
            out[group] = lists
    return out


# The race in the TimeScore post (mckoss.com/posts/timescore/): weekly views
# of the RACE_BY_TOTAL articles with the most views so far, and of the
# articles with the highest TimeScore now, at a half-life of RACE_HALF_LIFE
# weeks (the post's default), up to RACE_SERIES in all. The post ranks them
# both ways, so the two picks show what each ranking favors.
RACE_SERIES = 8
RACE_BY_TOTAL = 4
RACE_HALF_LIFE = 13
RACE_COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948']


def race(days):
    """The post's race: {"start": the first full week's Monday, "last": the
    last day counted, "series": [{"label", "link", "color", "counts": one
    total per full week}]}, the articles with the most views first; or None
    without a full week of data. A day an article missed the top 500 counts
    as no views."""
    first, last = days[0][0], days[-1][0]
    start = first + datetime.timedelta(days=-first.weekday() % 7)
    weeks = ((last - start).days + 1) // 7
    if weeks < 1:
        return None
    counts, titles = {}, {}
    for date, events in days:
        week = (date - start).days // 7
        if not 0 <= week < weeks:
            continue
        for key, (value, title) in events.items():
            counts.setdefault(key, [0] * weeks)[week] += value
            titles[key] = title

    def now(key):
        score = EMPTY
        for week, count in enumerate(counts[key]):
            if count > 0:
                score = add_event(score, count, week + 0.5, RACE_HALF_LIFE)
        return score_at(score, weeks, RACE_HALF_LIFE) if score != EMPTY else 0

    by_total = sorted(counts, key=lambda key: (-sum(counts[key]), key))
    picked = by_total[:RACE_BY_TOTAL]
    picked += [key for key in sorted(counts, key=lambda key: (-now(key), key))
               if key not in picked][:RACE_SERIES - len(picked)]
    picked.sort(key=by_total.index)
    return {
        'start': start.isoformat(),
        'last': (start + datetime.timedelta(weeks=weeks, days=-1)).isoformat(),
        'series': [{'label': titles[key], 'link': wikipages.link(key), 'color': RACE_COLORS[i],
                    'counts': [round(count) for count in counts[key]]}
                   for i, key in enumerate(picked)],
    }


SERIES_SHARDS = 128


def shard_of(key):
    """Which series file holds a key: FNV-1a of its UTF-8 bytes (app.js has the same)."""
    h = 0x811c9dc5
    for byte in key.encode('utf-8'):
        h = ((h ^ byte) * 0x01000193) & 0xffffffff
    return h % SERIES_SHARDS


def write_series(days, start, folder='site/data/wikipedia'):
    """Every article's daily values, sharded, and an index of all of them."""
    series, total = {}, {}
    for date, events in days:
        day = (date - start).days
        for key, (value, _) in events.items():
            series.setdefault(key, []).append([day, value])
            total[key] = total.get(key, 0) + value
    shards = [{} for _ in range(SERIES_SHARDS)]
    for key, points in series.items():
        shards[shard_of(key)][key.split(':', 1)[1]] = points
    os.makedirs(folder, exist_ok=True)
    for n, shard in enumerate(shards):
        with open(os.path.join(folder, f'series-{n:03d}.json'), 'w', encoding='utf-8') as f:
            json.dump({'start': start.isoformat(), 'series': shard}, f, ensure_ascii=False, separators=(',', ':'))
    with open(os.path.join(folder, 'index.json'), 'w', encoding='utf-8') as f:
        json.dump([key.split(':', 1)[1] for key in sorted(total, key=lambda k: -total[k])], f,
                  ensure_ascii=False, separators=(',', ':'))


def main():
    with open('VERSION', encoding='utf-8') as f:
        version = f.read().strip()
    out = {
        'version': version,
        'generated': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
        'halfLives': [{'label': label, 'days': days} for label, days in HALF_LIVES],
        'trending': TRENDING,
        'trendingMinDays': TRENDING_MIN_DAYS,
        'sources': {},
    }
    built = {}
    pools = {}
    for source in SOURCES:
        days = read_days(source)
        if days:
            built[source] = (days, *build_source(source, days, pools if source == 'wikipedia' else None))

    keys = set()
    for days, start, titles, lists, racers in built.values():
        keys |= racers | {item['key'] for items in lists.values() for item in items}
    found = posters.ensure(sorted(k for k in keys if not k.startswith('wikipedia:')))
    # Tag the articles that could make a topic's list, most-read first.
    rankings = [[key for key, _ in now] for now, _ in pools.values()]
    tagged = wikitopics.ensure(rankings, SHOWN) if rankings else {}
    topics = topic_lists(pools, {key: wikitopics.groups_of(row) for key, row in tagged.items()})
    keys |= {item['key'] for group in topics.values() for items in group.values() for item in items[:SHOWN]}
    pages = wikipages.ensure(sorted(k for k in keys if k.startswith('wikipedia:')))

    def describe(key, titles):
        source, ident = key.split(':', 1)
        if source == 'wikipedia':
            return article(key, titles[key], pages.get(key))
        row = found.get(key)
        # TMDB's export titles are original-language; prefer TMDB's English title.
        title = titles[key]
        if source == 'tmdb' and row and row.get('title'):
            title = row['title'] + (f' ({row["year"]})' if row.get('year') else '')
        return {'title': title, 'image': posters.url(row), 'link': SOURCES[source]['link'].format(id=ident)}

    for source, info in SOURCES.items():
        entry = {**info, 'collected': 0, 'start': None, 'last': None}
        if source in built:
            days, start, titles, lists, racers = built[source]
            shown = racers | {item['key'] for items in lists.values() for item in items[:SHOWN]}
            if source == 'wikipedia' and topics:
                entry['topics'] = [{'id': group, 'label': label}
                                   for group, label in wikitopics.GROUPS if group in topics]
                entry['topicLists'] = topics
                shown |= {item['key'] for group in topics.values() for items in group.values()
                          for item in items[:SHOWN]}
            entry.update({
                'collected': len(days),
                'start': start.isoformat(),
                'last': days[-1][0].isoformat(),
                'items': {key: describe(key, titles) for key in shown},
                'lists': lists,
                'racers': sorted(racers),
                'series': {key: [[(date - start).days, events[key][0]] for date, events in days if key in events]
                           for key in sorted(shown)},
            })
        out['sources'][source] = entry

    if 'wikipedia' in built:
        days, start = built['wikipedia'][:2]
        write_series(days, start)
        post_race = race(days)
        if post_race:
            os.makedirs('site/data', exist_ok=True)
            with open('site/data/race.json', 'w', encoding='utf-8') as f:
                json.dump(post_race, f, ensure_ascii=False, separators=(',', ':'))
    os.makedirs('site/data', exist_ok=True)
    with open('site/data/movies.json', 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, separators=(',', ':'))
    for source, entry in out['sources'].items():
        print(f"{source}: {entry['collected']} day(s), {entry['start']} to {entry['last']}")


if __name__ == '__main__':
    main()
