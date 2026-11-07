// The freshness line on each page: when the data was last updated, how far
// each source's data goes, and a warning when the daily update seems to
// have stopped.

const STALE_HOURS = 30;      // the daily update runs every 24 hours
const STALE_DATA_DAYS = 2;   // each source should have data from yesterday or today
const DAY_MS = 86400e3;

// — Freshness ——————————————————————————————————————————————————————————

export function showFreshness({ generated, sources }) {
  const element = document.querySelector('[data-freshness]');
  const built = new Date(generated);
  const hours = (Date.now() - built) / 3600e3;
  const ago = hours < 1 ? 'less than an hour ago'
    : hours < 48 ? `${Math.round(hours)} hour${Math.round(hours) === 1 ? '' : 's'} ago`
      : `${Math.round(hours / 24)} days ago`;
  const through = Object.values(sources)
    .map((s) => `${s.name}: ${s.last ? `through ${formatDate(s.last)}` : 'collecting'}`).join(' · ');
  // A source whose newest data is more than two days old has stopped
  // updating, even if the build itself ran.
  const today = new Date().toISOString().slice(0, 10);
  const behind = Object.values(sources)
    .filter((s) => s.last && daysBetween(s.last, today) > STALE_DATA_DAYS)
    .map((s) => `${s.name} has no data since ${formatDate(s.last)}`);
  const stale = hours > STALE_HOURS || behind.length > 0;
  element.classList.toggle('stale', stale);
  element.innerHTML = '';
  const status = document.createElement('strong');
  status.textContent = stale ? '⚠ Not updated recently' : '● Up to date';
  const detail = document.createElement('span');
  const problem = [hours > STALE_HOURS ? 'The daily update may have failed.' : '', ...behind.map((b) => `${b}.`)]
    .filter(Boolean).join(' ');
  detail.textContent = `Updated ${ago} (${built.toUTCString().slice(5, 22)} UTC). ${problem ? `${problem} ` : ''}${through}`;
  element.append(status, ' ', detail);
}

export function daysBetween(a, b) { return Math.round((Date.parse(b) - Date.parse(a)) / DAY_MS); }

export function formatDate(iso) {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });
}
