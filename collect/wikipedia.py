"""Daily Wikipedia collector: the most-read articles on English Wikipedia.

Wikimedia's Pageviews API lists the 1,000 most-viewed pages of English
Wikipedia for each day, back to 2015. This keeps the TOP articles of each day
in data/wikipedia/YYYY-MM-DD.tsv. Each run collects up to MAX_DAYS days not
yet collected, newest first, back to START: the first run collects the last
three months, and later runs fill in the rest of the history a few months a
day while keeping up with each new day.

Two things are left out:
- pages that aren't articles: the Main Page, searches, portals and other
  pages outside the article namespace;
- pages whose views look automated: nearly all from desktop computers, or
  nearly none, when real readers come about a third from desktop and the rest
  from phones. Wikimedia doesn't count known bots, but some automated traffic
  still gets through, and its pages swing in and out of the top lists.

Pageview data from the Wikimedia Foundation, released under CC0.
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

TOP_URL = 'https://wikimedia.org/api/rest_v1/metrics/pageviews/top/en.wikipedia/{access}/{d:%Y}/{d:%m}/{d:%d}'
START = datetime.date(2023, 11, 1)  # how far back to collect (about three years)
MAX_DAYS = 90                       # days collected per run
TOP = 500                           # articles kept per day
DESKTOP_MAX = 0.9                   # above this share of views from desktop: automated
DESKTOP_MIN = 0.03                  # below it: automated
PAUSE = 0.4                         # seconds between requests (Wikimedia allows 200 a minute)
BUDGET = 20 * 60                    # seconds a run may spend collecting; the rest waits for the next run

# Namespaces of English Wikipedia other than articles, and their aliases.
NAMESPACES = {
    'media', 'special', 'talk', 'user', 'user talk', 'wikipedia', 'wikipedia talk', 'wp', 'wt',
    'project', 'project talk', 'file', 'file talk', 'image', 'image talk', 'mediawiki',
    'mediawiki talk', 'template', 'template talk', 'help', 'help talk', 'category',
    'category talk', 'portal', 'portal talk', 'draft', 'draft talk', 'mos', 'mos talk',
    'timedtext', 'timedtext talk', 'module', 'module talk', 'event', 'event talk',
}
NOT_ARTICLES = {'Main_Page', '-', 'Undefined', 'Undefined_title'}


def user_agent():
    """Wikimedia asks for name/version (contact) library/version."""
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    try:
        with open(os.path.join(root, 'VERSION'), encoding='utf-8') as f:
            version = f.read().strip()
    except FileNotFoundError:
        version = '0'
    return (f'TimeScoreDemosBot/{version} (https://github.com/mckoss/timescore-demos) '
            f'python-urllib/{sys.version_info.major}.{sys.version_info.minor}')


USER_AGENT = user_agent()


def get_json(url, tries=6, missing_tries=3, body=None):
    """The JSON at url (POSTing body as JSON, if given), or None for a 404 (a
    day not published yet). Waits and tries again when Wikimedia says to slow
    down (429) or is busy (503), and on a 404 too, since Wikimedia sometimes
    says a published day is missing."""
    headers = {'User-Agent': USER_AGENT, 'Accept': 'application/json'}
    data = None
    if body is not None:
        headers['Content-Type'] = 'application/json'
        data = json.dumps(body).encode('utf-8')
    request = urllib.request.Request(url, data=data, headers=headers)
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                if attempt >= missing_tries - 1:
                    return None
                time.sleep(3 * (attempt + 1))
                continue
            if error.code not in (429, 503) or attempt == tries - 1:
                raise
            wait = error.headers.get('Retry-After')
            wait = int(wait) if wait and wait.isdigit() else 5 * 2 ** attempt
            print(f'Wikimedia said {error.code}; waiting {wait} s.', flush=True)
            time.sleep(wait + 1)
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == tries - 1:
                raise
            print(f'{error}; trying again.', flush=True)
            time.sleep(5 * 2 ** attempt)
    return None


def top_list(day, access):
    """{article: views} for the 1,000 most-viewed pages of a day, or None."""
    data = get_json(TOP_URL.format(access=access, d=day))
    time.sleep(PAUSE)
    if not data:
        return None
    return {item['article']: item['views'] for item in data['items'][0]['articles']}


def is_article(name):
    if name in NOT_ARTICLES:
        return False
    if ':' in name:
        prefix = name.split(':', 1)[0].replace('_', ' ').strip().lower()
        if prefix in NAMESPACES:
            return False
    return True


def desktop_share(name, views, desktop):
    """The share of a page's views from desktop, as (low, high) bounds: exact
    when the page is in the desktop top list, and otherwise at most the
    smallest count in that list."""
    if name in desktop:
        share = min(1.0, desktop[name] / views)
        return share, share
    return 0.0, min(1.0, min(desktop.values(), default=0) / views)


def automated(name, views, desktop):
    low, high = desktop_share(name, views, desktop)
    return low > DESKTOP_MAX or high < DESKTOP_MIN


def select(all_access, desktop):
    """The day's top articles as [(name, views)], most-viewed first, without
    non-articles and automated-looking pages; and how many were dropped."""
    kept, dropped = [], []
    for name, views in sorted(all_access.items(), key=lambda item: (-item[1], item[0])):
        if not is_article(name):
            continue
        if automated(name, views, desktop):
            dropped.append(name)
            continue
        kept.append((name, views))
    return kept[:TOP], dropped


def title_of(name):
    return ' '.join(name.replace('_', ' ').split())


def collect(day, out):
    path = os.path.join(out, f'{day.isoformat()}.tsv')
    if os.path.exists(path):
        return False
    all_access = top_list(day, 'all-access')
    desktop = top_list(day, 'desktop') if all_access is not None else None
    if desktop is None:
        print(f'No list for {day} from Wikimedia; the next run tries again.', flush=True)
        return False
    articles, dropped = select(all_access, desktop)
    os.makedirs(out, exist_ok=True)
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(f'# English Wikipedia pageviews on {day}, from the Wikimedia Foundation (CC0). '
                f'Left out as automated: {", ".join(dropped) or "none"}.\n')
        f.write('article\tviews\ttitle\n')
        for name, views in articles:
            f.write(f'{name}\t{views}\t{title_of(name)}\n')
    print(f'Wrote {path}: top {len(articles)} articles, {len(dropped)} left out as automated.', flush=True)
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--out', default='data/wikipedia')
    parser.add_argument('--start', type=datetime.date.fromisoformat, default=START,
                        help='the first day to collect (YYYY-MM-DD)')
    parser.add_argument('--max-days', type=int, default=MAX_DAYS,
                        help='the most days to collect in one run')
    parser.add_argument('--budget', type=float, default=BUDGET,
                        help='seconds to spend before stopping; the next run continues')
    args = parser.parse_args()
    today = datetime.datetime.now(datetime.timezone.utc).date()
    began = time.monotonic()
    collected = 0
    # Newest first, so the latest day is never held up by the backfill.
    day = today - datetime.timedelta(days=1)
    while day >= args.start and collected < args.max_days:
        if time.monotonic() - began > args.budget:
            print('Out of time; the next run continues.')
            break
        collected += collect(day, args.out)
        day -= datetime.timedelta(days=1)
    print(f'Collected {collected} new day(s) of Wikipedia data.')


if __name__ == '__main__':
    main()
