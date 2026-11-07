// The update log page: totals for the data in the repository, and a row for
// each update with the data it added. Reads site/data/status.json, written
// by build/log.py, and movies.json for the freshness line.

import { showFreshness, formatDate } from './freshness.js';

const NAMES = { imdb: 'New IMDb ratings', tmdb: 'TMDB popularity' };
const TRIGGERS = {
  schedule: 'Daily schedule',
  push: 'Code change',
  workflow_dispatch: 'Run by hand',
  history: 'From history',
  local: 'Local run',
};

const [status, movies] = await Promise.all([
  fetch(`data/status.json?v=${Date.now()}`).then((r) => r.json()),
  fetch(`data/movies.json?v=${Date.now()}`).then((r) => r.json()),
]);
showFreshness(movies);
showTotals(status);
showLog(status.log);

function showTotals({ totals, runs }) {
  const element = document.querySelector('[data-totals]');
  if (!totals) return;
  const cards = Object.keys(NAMES).map((source) => {
    const t = totals[source];
    return card(NAMES[source], t.days ? `${t.days} day${t.days === 1 ? '' : 's'}` : 'None yet',
      t.days ? `${formatDate(t.first)} to ${formatDate(t.last)} · ${formatBytes(t.bytes)}` : 'Collecting');
  });
  cards.push(card('Posters', String(totals.posters), 'Looked up from TMDB'));
  cards.push(card('All data', formatBytes(totals.bytes), `${runs} update${runs === 1 ? '' : 's'} logged`));
  element.append(...cards);
}

function card(title, value, detail) {
  const div = document.createElement('div');
  div.className = 'total';
  const h = document.createElement('h3');
  h.textContent = title;
  const v = document.createElement('p');
  v.className = 'total-value';
  v.textContent = value;
  const d = document.createElement('p');
  d.className = 'total-detail';
  d.textContent = detail;
  div.append(h, v, d);
  return div;
}

function showLog(log) {
  const body = document.querySelector('[data-log]');
  for (const item of log) {
    const row = document.createElement('tr');
    const when = new Date(item.time);
    const ran = item.run ? link(item.run, formatTime(when)) : text(formatTime(when));
    row.append(
      cell(ran),
      cell(text(TRIGGERS[item.trigger] || item.trigger)),
      cell(added(item.added.imdb)),
      cell(added(item.added.tmdb)),
      cell(text(item.posters ? `+${item.posters}` : '—')),
      cell(text(formatBytes(item.totals.bytes))),
    );
    if (!item.added.imdb.days.length && !item.added.tmdb.days.length) row.className = 'nothing-new';
    body.append(row);
  }
}

// "Nov 6: 500 movies, 18 KB" (or "Jul 27 to Nov 3: 100 days, …" for a range).
function added({ days, rows, bytes }) {
  if (!days.length) return text('—');
  const span = days.length === 1 ? formatDate(days[0]).replace(/, \d{4}$/, '')
    : `${formatDate(days[0]).replace(/, \d{4}$/, '')} to ${formatDate(days[days.length - 1]).replace(/, \d{4}$/, '')} (${days.length} days)`;
  return text(`${span}: ${rows.toLocaleString('en-US')} movies, ${formatBytes(bytes)}`);
}

function cell(content) {
  const td = document.createElement('td');
  td.append(content);
  return td;
}

function text(value) { return document.createTextNode(value); }

function link(href, label) {
  const a = document.createElement('a');
  a.href = href;
  a.textContent = label;
  return a;
}

function formatTime(date) {
  return `${date.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' })}, `
    + date.toISOString().slice(11, 16);
}

function formatBytes(bytes) {
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`;
  if (bytes >= 1e3) return `${Math.round(bytes / 1e3)} KB`;
  return `${bytes} B`;
}
