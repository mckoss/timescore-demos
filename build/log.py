"""The update log: what each run of the daily workflow added to the data.

Run after the collectors and the build, before the data is committed:

    python build/log.py

It looks at what the run changed under data/ and appends one line to
data/log.jsonl: when it ran, what started it, the data days each source
added (with their rows and bytes), the posters it looked up, and the totals
for the whole repository. Then it writes site/data/status.json, which the
update log page (site/status.html) shows.

    python build/log.py --backfill

rebuilds data/log.jsonl from the data commits in git history instead (for
the runs before the log existed), then writes site/data/status.json.
"""

import argparse
import datetime
import json
import os
import subprocess

SOURCES = ('imdb', 'tmdb', 'wikipedia')
LOG = 'data/log.jsonl'
POSTERS = 'data/posters.tsv'
SHOWN = 120   # log entries on the page


def git(*args):
    return subprocess.run(['git', *args], check=True, capture_output=True, text=True).stdout


def data_rows(text):
    """Rows in a data file: lines that aren't comments, less the header."""
    return max(0, sum(1 for line in text.splitlines() if line and not line.startswith('#')) - 1)


def source_of(path):
    parts = path.split('/')
    if len(parts) == 3 and parts[0] == 'data' and parts[1] in SOURCES and parts[2].endswith('.tsv'):
        return parts[1]
    return None


def totals(files):
    """Totals for the data in the repository, from {path: (bytes, text or None)}."""
    out = {'bytes': sum(size for path, (size, _) in files.items() if path != LOG)}
    for source in SOURCES:
        days = sorted(os.path.basename(p)[:-4] for p in files if source_of(p) == source)
        out[source] = {
            'days': len(days),
            'first': days[0] if days else None,
            'last': days[-1] if days else None,
            'bytes': sum(size for p, (size, _) in files.items() if source_of(p) == source),
        }
    posters = files.get(POSTERS)
    out['posters'] = data_rows(posters[1]) if posters and posters[1] is not None else 0
    return out


def entry(time, trigger, run, added_files, posters_added, all_files):
    added = {}
    for source in SOURCES:
        mine = {p: v for p, v in added_files.items() if source_of(p) == source}
        added[source] = {
            'days': sorted(os.path.basename(p)[:-4] for p in mine),
            'rows': sum(data_rows(text) for _, text in mine.values()),
            'bytes': sum(size for size, _ in mine.values()),
        }
    return {'time': time, 'trigger': trigger, 'run': run, 'version': current_version(),
            'added': added, 'posters': posters_added, 'totals': totals(all_files)}


def current_version():
    """The code's version (VERSION), or None before there was one."""
    try:
        with open('VERSION', encoding='utf-8') as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def current_entry():
    """This run's entry, from the uncommitted changes under data/."""
    changed = [line[3:] for line in git('status', '--porcelain', '--untracked-files=all', 'data').splitlines()]
    added = {}
    for path in changed:
        if source_of(path):
            with open(path, encoding='utf-8') as f:
                added[path] = (os.path.getsize(path), f.read())
    before = 0
    try:
        before = data_rows(git('show', f'HEAD:{POSTERS}'))
    except subprocess.CalledProcessError:
        pass
    files = {}
    for root, _, names in os.walk('data'):
        for name in names:
            path = os.path.join(root, name)
            text = None
            if path == POSTERS:
                with open(path, encoding='utf-8') as f:
                    text = f.read()
            files[path] = (os.path.getsize(path), text)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
    run = None
    if os.environ.get('GITHUB_RUN_ID'):
        run = (f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
               f"{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ['GITHUB_RUN_ID']}")
    posters_now = totals(files)['posters']
    return entry(now, os.environ.get('GITHUB_EVENT_NAME', 'local'), run, added,
                 max(0, posters_now - before), files)


def history_entries():
    """An entry for each commit that changed data/, oldest first."""
    entries = []
    previous_posters = 0
    for line in git('log', '--reverse', '--format=%H %cI', '--', 'data').splitlines():
        commit, time = line.split(' ', 1)
        if commit == '':
            continue
        added = {}
        for change in git('diff-tree', '--root', '--no-commit-id', '--name-status', '-r', commit, '--', 'data').splitlines():
            status, path = change.split('\t', 1)
            if status.startswith('A') and source_of(path):
                added[path] = (int(git('cat-file', '-s', f'{commit}:{path}')), git('show', f'{commit}:{path}'))
        files = {}
        for item in git('ls-tree', '-r', '-l', commit, 'data').splitlines():
            meta, path = item.split('\t', 1)
            size = int(meta.split()[3])
            files[path] = (size, git('show', f'{commit}:{path}') if path == POSTERS else None)
        posters_now = totals(files)['posters']
        time = datetime.datetime.fromisoformat(time).astimezone(datetime.timezone.utc).isoformat(timespec='seconds')
        item = entry(time, 'history', None, added, max(0, posters_now - previous_posters), files)
        item['version'] = None   # before versions
        entries.append(item)
        previous_posters = posters_now
    return entries


def data_dates():
    """Every date each source has data for, from the files in data/."""
    return {source: sorted(name[:-4] for name in os.listdir(os.path.join('data', source))
                           if name.endswith('.tsv'))
            if os.path.isdir(os.path.join('data', source)) else []
            for source in SOURCES}


def write_status(entries):
    os.makedirs('site/data', exist_ok=True)
    status = {
        'generated': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'),
        'totals': entries[-1]['totals'] if entries else None,
        'runs': len(entries),
        'version': current_version(),
        'dates': data_dates(),
        'log': list(reversed(entries))[:SHOWN],
    }
    with open('site/data/status.json', 'w', encoding='utf-8') as f:
        json.dump(status, f, separators=(',', ':'))


def read_log():
    if not os.path.exists(LOG):
        return []
    with open(LOG, encoding='utf-8') as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--backfill', action='store_true',
                        help='rebuild the log from the data commits in git history')
    args = parser.parse_args()
    if args.backfill:
        entries = history_entries()
        with open(LOG, 'w', encoding='utf-8') as f:
            for item in entries:
                f.write(json.dumps(item, separators=(',', ':')) + '\n')
    else:
        entries = read_log()
        item = current_entry()
        entries.append(item)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(item, separators=(',', ':')) + '\n')
    write_status(entries)
    last = entries[-1]
    print(f"Logged {len(entries)} run(s); latest added "
          + ', '.join(f"{s} {len(last['added'][s]['days'])} day(s)" for s in SOURCES)
          + f", {last['posters']} poster(s).")


if __name__ == '__main__':
    main()
