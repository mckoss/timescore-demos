"""Daily Polymarket collector: the events with the most money traded.

Polymarket's public market API (Gamma) lists markets sorted by how many
dollars changed hands in the last 24 hours, and each market carries its
event's own 24-hour total across all of the event's markets (an election
with a market per candidate, a game with markets on the winner and the
score). This reads the busiest open markets, and the busiest closed ones
(a game that ended overnight still had its biggest day), and keeps the TOP
events of the day in data/polymarket/YYYY-MM-DD.tsv.

A run covers the 24 hours before it, so its file is dated by the middle of
that window: the daily 09:41 UTC run collects yesterday. A day that's
already collected is skipped, and one that's missed is gone (Polymarket
doesn't publish daily history).

It also looks up each event's tags once (Sports, Crypto, Politics…), keeping
the ones that map to the site's topics (GROUPS) in data/polymarket-tags.tsv.

Market data from Polymarket; this site isn't affiliated with Polymarket.
"""

import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

sys.dont_write_bytecode = True

MARKETS = 'https://gamma-api.polymarket.com/markets'
EVENT_TAGS = 'https://gamma-api.polymarket.com/events/{id}/tags'
TAGS = 'data/polymarket-tags.tsv'
TAG_LOOKUPS = 1000    # events tagged per run, at most; the rest wait for the next run
PAGE = 100            # the API's page size
OPEN_PAGES = 10       # the 1,000 busiest open markets
CLOSED_PAGES = 5      # and the 500 busiest closed ones
TOP = 300             # events kept per day
PAUSE = 0.5           # seconds between requests


def user_agent():
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    try:
        with open(os.path.join(root, 'VERSION'), encoding='utf-8') as f:
            version = f.read().strip()
    except FileNotFoundError:
        version = '0'
    return (f'TimeScoreDemosBot/{version} (https://github.com/mckoss/timescore-demos) '
            f'python-urllib/{sys.version_info.major}.{sys.version_info.minor}')


def get_json(url, tries=6):
    """The JSON at url, waiting and trying again when told to slow down."""
    request = urllib.request.Request(url, headers={'User-Agent': user_agent(), 'Accept': 'application/json'})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == tries - 1:
                raise
            wait = error.headers.get('Retry-After')
            wait = int(wait) if wait and wait.isdigit() else 5 * 2 ** attempt
            print(f'Polymarket said {error.code}; waiting {wait} s.', flush=True)
            time.sleep(wait)
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == tries - 1:
                raise
            print(f'{error}; trying again.', flush=True)
            time.sleep(5 * 2 ** attempt)
    return None


def busiest_markets():
    """The busiest open and closed markets by 24-hour volume."""
    markets = []
    for closed, pages in (('false', OPEN_PAGES), ('true', CLOSED_PAGES)):
        for page in range(pages):
            query = {'closed': closed, 'order': 'volume24hr', 'ascending': 'false',
                     'limit': PAGE, 'offset': page * PAGE}
            if closed == 'false':
                query['active'] = 'true'
            batch = get_json(f'{MARKETS}?{urllib.parse.urlencode(query)}') or []
            markets += batch
            time.sleep(PAUSE)
            if len(batch) < PAGE:
                break
    return markets


def number(value):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def clean(text):
    return ' '.join(str(text or '').split())


def events_of(markets):
    """{event id: (dollars traded in 24 hours, slug, title)} from markets.
    An event's own 24-hour total covers all its markets; if it's missing,
    the event gets the sum of the markets seen here."""
    totals, sums = {}, {}
    for market in markets:
        for event in market.get('events') or []:
            ident = str(event.get('id') or '')
            if not ident or not event.get('slug'):
                continue
            sums[ident] = sums.get(ident, 0.0) + number(market.get('volume24hr'))
            own = number(event.get('volume24hr'))
            previous = totals.get(ident, (0.0, '', ''))
            totals[ident] = (max(own, previous[0]), clean(event['slug']), clean(event.get('title')) or clean(event['slug']))
    return {ident: (volume if volume > 0 else sums[ident], slug, title)
            for ident, (volume, slug, title) in totals.items()}


def top_events(events, n=TOP):
    """The n events with the most volume, most first: [(id, dollars, slug, title)]."""
    ranked = sorted(((ident, round(volume), slug, title) for ident, (volume, slug, title) in events.items()
                     if volume >= 1), key=lambda row: (-row[1], row[0]))
    return ranked[:n]


def collect(now, out):
    day = (now - datetime.timedelta(hours=12)).date()
    path = os.path.join(out, f'{day.isoformat()}.tsv')
    if os.path.exists(path):
        print(f'{path} is already collected.')
        return False
    rows = top_events(events_of(busiest_markets()))
    if not rows:
        print('Polymarket returned no markets; nothing collected.')
        return False
    os.makedirs(out, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(f'# Dollars traded on Polymarket events in the 24 hours to {now:%Y-%m-%d %H:%M} UTC. '
                'Market data from Polymarket.\n')
        f.write('event_id\tdollars\tslug\ttitle\n')
        for ident, dollars, slug, title in rows:
            f.write(f'{ident}\t{dollars}\t{slug}\t{title}\n')
    print(f'Wrote {path}: top {len(rows)} events.')
    return True


# — Topics ————————————————————————————————————————————————————————————————

# The topics the site shows, from Polymarket's tags (an event can be in
# several). Esports events are also tagged Sports, so Sports leaves them out.
GROUPS = [
    ('sports', 'Sports'),
    ('esports', 'Esports'),
    ('crypto', 'Crypto'),
    ('politics', 'Politics'),
    ('world', 'World'),
    ('economy', 'Economy'),
    ('tech', 'Tech & science'),
    ('culture', 'Culture'),
]
TAG_GROUPS = {
    'sports': {'sports'},
    'esports': {'esports'},
    'crypto': {'crypto', 'crypto-prices', 'bitcoin', 'ethereum', 'solana', 'xrp'},
    'politics': {'politics', 'elections', 'us-politics', 'trump', 'us-presidential-election',
                 'global-elections', 'world-elections', 'congress', 'midterms'},
    'world': {'geopolitics', 'world', 'middle-east', 'ukraine', 'russia', 'iran', 'israel', 'china',
              'diplomacy-ceasefire', 'gaza'},
    'economy': {'economy', 'finance', 'fed', 'fed-rates', 'business', 'stocks', 'economic-policy',
                'inflation', 'earnings', 'commodities'},
    'tech': {'tech', 'ai', 'science', 'space', 'openai', 'big-tech'},
    'culture': {'pop-culture', 'culture', 'movies', 'music', 'celebrities', 'awards', 'mentions',
                'tweet-markets', 'entertainment'},
}
KEPT_TAGS = set().union(*TAG_GROUPS.values())


def groups_of(tags):
    """The ids of the GROUPS an event with these tag slugs is in."""
    tags = set(tags or ())
    groups = {group for group, wanted in TAG_GROUPS.items() if tags & wanted}
    if 'esports' in groups:
        groups.discard('sports')
    return groups


def load_tags(path=TAGS):
    """{event id: [tag slug, …]} from the cache."""
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        rows = [line.rstrip('\n').split('\t') for line in f.read().splitlines()[1:] if line]
    return {row[0]: [tag for tag in row[1].split(';') if tag] for row in rows}


def save_tags(tags, path=TAGS):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write('event_id\ttags\n')
        for ident in sorted(tags, key=lambda i: (len(i), i)):
            f.write(f'{ident}\t{";".join(sorted(tags[ident]))}\n')


def tag_events(out, path=TAGS, limit=TAG_LOOKUPS):
    """Looks up the tags of collected events not in the cache yet (up to limit)."""
    tags = load_tags(path)
    missing = []
    for name in sorted(os.listdir(out), reverse=True) if os.path.isdir(out) else []:
        if not name.endswith('.tsv'):
            continue
        with open(os.path.join(out, name), encoding='utf-8') as f:
            for line in f.read().splitlines()[2:]:
                ident = line.split('\t', 1)[0]
                if ident and ident not in tags and ident not in missing:
                    missing.append(ident)
    looked_up = 0
    for ident in missing[:limit]:
        try:
            found = get_json(EVENT_TAGS.format(id=urllib.parse.quote(ident))) or []
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
            found = []
        tags[ident] = sorted({t.get('slug') for t in found if t.get('slug') in KEPT_TAGS})
        looked_up += 1
        time.sleep(PAUSE / 2)
    if looked_up:
        save_tags(tags, path)
    print(f'Looked up the tags of {looked_up} event(s)'
          + (f'; {len(missing) - looked_up} wait for the next run.' if len(missing) > looked_up else '.'))
    return tags


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', default='data/polymarket')
    args = parser.parse_args()
    collect(datetime.datetime.now(datetime.timezone.utc), args.out)
    tag_events(args.out)


if __name__ == '__main__':
    main()
