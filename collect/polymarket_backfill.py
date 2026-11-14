"""One-time Polymarket backfill from Dune: the top events of each past day.

Polymarket doesn't publish daily volume history, but its trades are on the
Polygon blockchain, and Dune (dune.com) indexes them: polymarket_polygon.
market_trades_raw has every fill, and polymarket.gamma_markets_0001 maps each
market to its Polymarket event (the same ids, slugs and titles as
collect/polymarket.py's daily files) and the event's tags. Summing every
fill's dollar amount matches Polymarket's own volume figures (both sides of
each trade) within a few percent.

This writes data/polymarket/YYYY-MM-DD.tsv for each UTC day from --start up
to --stop (not including it) that isn't collected yet, with the TOP events
of the day, and adds the events' topic tags to data/polymarket-tags.tsv. It
runs in quarterly chunks and needs a Dune API key with Read scope: the
DUNE_API_KEY environment variable, or one added to requests by a proxy.

    python collect/polymarket_backfill.py --start 2023-11-01 --stop 2026-11-14
"""

import argparse
import datetime
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import polymarket  # noqa: E402

API = 'https://api.dune.com/api/v1'
TOP = polymarket.TOP

SQL = """
WITH m AS (
  SELECT DISTINCT from_hex(substr(condition_id, 3)) AS cid, event_id
  FROM polymarket.gamma_markets_0001
  WHERE event_id IS NOT NULL AND condition_id LIKE '0x%'
),
d AS (
  SELECT CAST(date_trunc('day', t.block_time) AS date) AS day, m.event_id, sum(t.amount) AS dollars
  FROM polymarket_polygon.market_trades_raw t
  JOIN m ON t.condition_id = m.cid
  WHERE t.block_month BETWEEN DATE '{month_from}' AND DATE '{month_to}'
    AND t.block_time >= TIMESTAMP '{start} 00:00:00 UTC' AND t.block_time < TIMESTAMP '{stop} 00:00:00 UTC'
  GROUP BY 1, 2
),
r AS (SELECT day, event_id, dollars, row_number() OVER (PARTITION BY day ORDER BY dollars DESC) AS rn FROM d),
e AS (
  SELECT event_id, max(event_slug) AS slug, max(event_title) AS title, max(raw_event_json) AS raw
  FROM polymarket.gamma_markets_0001 GROUP BY 1
)
SELECT r.day, r.event_id, CAST(round(r.dollars) AS bigint) AS dollars, e.slug, e.title,
       array_join(filter(transform(CAST(json_extract(e.raw, '$.tags') AS array(json)),
                                   t -> json_extract_scalar(t, '$.slug')),
                         s -> s IN ({kept})), ';') AS tags
FROM r LEFT JOIN e ON e.event_id = r.event_id
WHERE r.rn <= {top} AND r.dollars >= 1
ORDER BY r.day, r.dollars DESC
"""


def call(method, path, body=None):
    headers = {'Content-Type': 'application/json', 'User-Agent': polymarket.user_agent(),
               'X-Dune-Api-Key': os.environ.get('DUNE_API_KEY', 'proxy-injected')}
    request = urllib.request.Request(API + path, method=method, headers=headers,
                                     data=json.dumps(body).encode() if body is not None else None)
    for attempt in range(6):
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503) or attempt == 5:
                raise SystemExit(f'Dune: {error.code} {error.read()[:300]!r}')
            time.sleep(5 * 2 ** attempt)


def run(sql):
    """The rows of a query, and the credits it used."""
    execution = call('POST', '/sql/execute', {'sql': sql, 'performance': 'medium'})['execution_id']
    while True:
        status = call('GET', f'/execution/{execution}/status')
        if status['state'] in ('QUERY_STATE_COMPLETED', 'QUERY_STATE_FAILED', 'QUERY_STATE_CANCELLED'):
            break
        time.sleep(5)
    if status['state'] != 'QUERY_STATE_COMPLETED':
        raise SystemExit(f'Dune query {status["state"]}: {json.dumps(status.get("error"))[:500]}')
    rows, offset = [], 0
    while offset is not None:
        result = call('GET', f'/execution/{execution}/results?limit=32000&offset={offset}')
        rows += result['result']['rows']
        offset = result.get('next_offset')
    return rows, status.get('execution_cost_credits')


def chunks(start, stop, months=3):
    """[start, stop) in pieces of about three calendar months."""
    while start < stop:
        year, month = start.year + (start.month - 1 + months) // 12, (start.month - 1 + months) % 12 + 1
        end = min(datetime.date(year, month, 1), stop)
        yield start, end
        start = end


def write_day(day, rows, out):
    path = os.path.join(out, f'{day}.tsv')
    if os.path.exists(path):
        return False
    with open(path, 'w', encoding='utf-8', newline='') as f:
        f.write(f'# Dollars traded on Polymarket events on {day} (UTC), from its trades on Polygon '
                'as indexed by Dune. Market data from Polymarket.\n')
        f.write('event_id\tdollars\tslug\ttitle\n')
        for row in rows:
            f.write(f'{row["event_id"]}\t{row["dollars"]}\t{polymarket.clean(row["slug"])}\t'
                    f'{polymarket.clean(row["title"]) or polymarket.clean(row["slug"])}\n')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--start', type=datetime.date.fromisoformat, required=True)
    parser.add_argument('--stop', type=datetime.date.fromisoformat, required=True,
                        help='the day after the last one to backfill')
    parser.add_argument('--out', default='data/polymarket')
    args = parser.parse_args()
    os.makedirs(args.out, exist_ok=True)
    kept = ', '.join(f"'{tag}'" for tag in sorted(polymarket.KEPT_TAGS))
    tags = polymarket.load_tags()
    total = 0.0
    for start, stop in chunks(args.start, args.stop):
        sql = SQL.format(start=start, stop=stop, month_from=start.replace(day=1),
                         month_to=(stop - datetime.timedelta(days=1)).replace(day=1), kept=kept, top=TOP)
        rows, credits = run(sql)
        total += credits or 0
        by_day = {}
        for row in rows:
            if row.get('slug'):
                by_day.setdefault(row['day'][:10], []).append(row)
                tags.setdefault(str(row['event_id']), [t for t in (row.get('tags') or '').split(';') if t])
        written = sum(write_day(day, day_rows, args.out) for day, day_rows in sorted(by_day.items()))
        polymarket.save_tags(tags)
        print(f'{start} to {stop}: {len(rows)} rows, {written} new day(s), {credits} credits '
              f'({total:.1f} so far).', flush=True)


if __name__ == '__main__':
    main()
