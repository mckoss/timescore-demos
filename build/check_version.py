"""Checks that a pull request that changes code raises the version.

    python build/check_version.py origin/main

Code is everything but the data the daily workflow commits (data/ and
site/data/). If the pull request changes any of it, VERSION must hold a
semantic version (MAJOR.MINOR.PATCH) higher than the base's, and
CHANGELOG.md must have a "## [MAJOR.MINOR.PATCH]" entry for it.
"""

import re
import subprocess
import sys

DATA = ('data/', 'site/data/')
SEMVER = re.compile(r'^(\d+)\.(\d+)\.(\d+)$')


def parse(version):
    """(major, minor, patch), or None if version isn't MAJOR.MINOR.PATCH."""
    match = SEMVER.match(version.strip())
    return tuple(int(part) for part in match.groups()) if match else None


def git(*args):
    return subprocess.run(['git', *args], check=True, capture_output=True, text=True).stdout


def problems(changed, base_version, version, changelog):
    """What's wrong, as a list of messages (empty when all is well)."""
    code = [path for path in changed if not path.startswith(DATA)]
    if not code:
        return []
    found = []
    new = parse(version)
    if new is None:
        return [f'VERSION is "{version.strip()}", not MAJOR.MINOR.PATCH.']
    old = parse(base_version) if base_version is not None else None
    if old is not None and new <= old:
        found.append(f'Code changed ({", ".join(code[:5])}{", …" if len(code) > 5 else ""}), '
                     f'so VERSION must be higher than {base_version.strip()}; it is {version.strip()}.')
    if f'## [{version.strip()}]' not in changelog:
        found.append(f'CHANGELOG.md has no "## [{version.strip()}]" entry.')
    return found


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else 'origin/main'
    changed = git('diff', '--name-only', f'{base}...HEAD').split()
    try:
        base_version = git('show', f'{base}:VERSION')
    except subprocess.CalledProcessError:
        base_version = None   # the base has no VERSION yet
    with open('VERSION', encoding='utf-8') as f:
        version = f.read()
    with open('CHANGELOG.md', encoding='utf-8') as f:
        changelog = f.read()
    found = problems(changed, base_version, version, changelog)
    for message in found:
        print(f'::error::{message}')
    if found:
        sys.exit(1)
    print(f'Version {version.strip()} is fine.')


if __name__ == '__main__':
    main()
