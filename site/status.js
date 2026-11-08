// The update log page: whether the daily update is running as expected, a
// chart of which days have data, a chart of the data's growth, totals, and
// a row for each update. Reads site/data/status.json, written by
// build/log.py.
//
// The health check runs here, in the reader's browser, against the current
// time, so it notices a missed update even when the workflow has stopped
// and this page itself hasn't changed.

import { formatDate, showVersion } from './freshness.js?v=__VERSION__';

const NAMES = { imdb: 'New IMDb ratings', tmdb: 'TMDB popularity', wikipedia: 'Wikipedia pageviews' };
const SHORT = { imdb: 'IMDb data', tmdb: 'TMDB data', wikipedia: 'Wikipedia data' };
// Days a source's newest data trails today. Wikimedia publishes a day's
// pageviews after the next day's update has run, so yesterday is normal there.
const LAG_DAYS = { imdb: 0, tmdb: 0, wikipedia: 1 };
const NOUNS = { imdb: 'movies', tmdb: 'movies', wikipedia: 'articles' };
const NOTHING = { days: [], rows: 0, bytes: 0 };   // a source an older log entry predates
const TRIGGERS = {
  schedule: 'Daily schedule',
  push: 'Code change',
  workflow_dispatch: 'Run by hand',
  history: 'From history',
  local: 'Local run',
};
const ACTIONS = 'https://github.com/mckoss/timescore-demos/actions/workflows/daily.yml';
const SCHEDULE_MINUTES = 9 * 60 + 41;  // the workflow runs daily at 09:41 UTC
const GRACE_MINUTES = 90;              // GitHub can start scheduled runs late
const STALE_DATA_DAYS = 2;             // each source should have data from yesterday or today
const CHART_DAYS = 60;
const DAY_MS = 86400e3;
const SVG = 'http://www.w3.org/2000/svg';

const status = await fetch(`data/status.json?v=${Date.now()}`).then((r) => r.json());
const now = new Date();
showHealth(status);
showCoverage(status);
showGrowth(status.log);
showTotals(status);
showLog(status.log);
showVersion(status.version);

// — Health ——————————————————————————————————————————————————————————————

function utcDay(date) { return date.toISOString().slice(0, 10); }
function addDays(day, n) { return utcDay(new Date(Date.parse(`${day}T00:00:00Z`) + n * DAY_MS)); }
function scheduledAt(day) { return new Date(Date.parse(`${day}T00:00:00Z`) + SCHEDULE_MINUTES * 60e3); }

// The latest day whose scheduled update should have run by now.
function lastExpectedDay() {
  const today = utcDay(now);
  const due = scheduledAt(today).getTime() + GRACE_MINUTES * 60e3;
  return now.getTime() >= due ? today : addDays(today, -1);
}

// Days since the log began, up to the latest expected one, with no update.
function missedDays(log) {
  if (!log.length) return [];
  const ran = new Set(log.map((item) => item.time.slice(0, 10)));
  const first = log[log.length - 1].time.slice(0, 10);
  const missed = [];
  for (let day = first; day <= lastExpectedDay(); day = addDays(day, 1)) {
    if (!ran.has(day)) missed.push(day);
  }
  return missed;
}

function showHealth({ log, dates }) {
  const element = document.querySelector('[data-health]');
  const problems = [];
  const last = log.length ? new Date(log[0].time) : null;
  const expected = scheduledAt(lastExpectedDay());
  if (!last || last < new Date(expected.getTime() - 5 * 60e3)) {
    problems.push(`The update due ${formatTime(expected)} UTC didn't run`
      + (last ? `; the last one ran ${ago(last)}.` : '.'));
  }
  const missed = missedDays(log).filter((day) => !last || day !== utcDay(expected));
  if (missed.length) {
    problems.push(`No update ran on ${missed.map((day) => formatDate(day).replace(/, \d{4}$/, '')).join(', ')}.`);
  }
  for (const [source, days] of Object.entries(dates)) {
    const newest = days[days.length - 1];
    if (newest && addDays(newest, STALE_DATA_DAYS) < utcDay(now)) {
      problems.push(`${NAMES[source]} has no data since ${formatDate(newest)}.`);
    }
  }

  element.innerHTML = '';
  element.classList.toggle('health-error', problems.length > 0);
  element.classList.toggle('health-ok', problems.length === 0);
  const badge = document.createElement('strong');
  badge.className = 'health-badge';
  const detail = document.createElement('div');
  detail.className = 'health-detail';
  if (problems.length) {
    badge.textContent = '✕ Missed update';
    for (const problem of problems) {
      const p = document.createElement('p');
      p.textContent = problem;
      detail.append(p);
    }
    const p = document.createElement('p');
    p.append('Check the ', link(ACTIONS, 'workflow runs'), ' on GitHub.');
    detail.append(p);
  } else {
    badge.textContent = '✓ All running as expected';
    const next = scheduledAt(now >= scheduledAt(utcDay(now)) ? addDays(utcDay(now), 1) : utcDay(now));
    const p = document.createElement('p');
    p.textContent = `Last update ${ago(last)} (${formatTime(last)} UTC). `
      + `Next scheduled update ${formatTime(next)} UTC, ${until(next)}.`;
    detail.append(p);
  }
  element.append(badge, detail);
}

function ago(date) {
  const minutes = Math.round((now - date) / 60e3);
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? '' : 's'} ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} hour${hours === 1 ? '' : 's'} ago`;
  return `${Math.round(hours / 24)} days ago`;
}

function until(date) {
  const minutes = Math.max(0, Math.round((date - now) / 60e3));
  const hours = Math.floor(minutes / 60);
  return `in ${hours ? `${hours} h ` : ''}${minutes % 60} min`;
}

// — Coverage chart ——————————————————————————————————————————————————————

function svg(tag, attrs = {}, title) {
  const element = document.createElementNS(SVG, tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  if (title) {
    const t = document.createElementNS(SVG, 'title');
    t.textContent = title;
    element.append(t);
  }
  return element;
}

function showCoverage({ log, dates }) {
  const today = utcDay(now);
  const start = addDays(today, -(CHART_DAYS - 1));
  const days = Array.from({ length: CHART_DAYS }, (_, i) => addDays(start, i));
  const runs = new Map();
  for (const item of log) {
    const day = item.time.slice(0, 10);
    runs.set(day, (runs.get(day) || 0) + 1);
  }
  const logStart = log.length ? log[log.length - 1].time.slice(0, 10) : today;
  const expectedUntil = lastExpectedDay();

  const rows = [
    { label: 'Updates', className: 'cell-runs', state: (day) => {
      if (runs.has(day)) return ['done', `${runs.get(day)} update${runs.get(day) === 1 ? '' : 's'}`];
      if (day < logStart) return ['none', 'Before the log began'];
      if (day > expectedUntil) return ['pending', 'Not due yet'];
      return ['missing', 'No update ran'];
    } },
    ...Object.keys(SHORT).map((source) => {
      const have = new Set(dates[source] || []);
      const first = (dates[source] || [])[0];
      return { label: SHORT[source], className: `cell-${source}`, state: (day) => {
        if (have.has(day)) return ['done', `${NAMES[source]} for this day`];
        if (!first || day < first) return ['none', 'Before collecting began'];
        if (day >= addDays(today, -LAG_DAYS[source])) return ['pending', 'Not out yet'];
        return ['missing', 'No data for this day'];
      } };
    }),
  ];

  const cell = 16;
  const gap = 3;
  const labelWidth = 92;
  const top = 4;
  const width = labelWidth + CHART_DAYS * (cell + gap);
  const height = top + rows.length * (cell + gap) + 24;
  const chart = svg('svg', { viewBox: `0 0 ${width} ${height}`, class: 'coverage', role: 'img',
    'aria-label': 'Which of the last 60 days had an update, IMDb data, TMDB data and Wikipedia data' });

  rows.forEach((row, r) => {
    const y = top + r * (cell + gap);
    const label = svg('text', { x: labelWidth - 10, y: y + cell / 2, class: 'chart-label', 'text-anchor': 'end', 'dominant-baseline': 'central' });
    label.textContent = row.label;
    chart.append(label);
    days.forEach((day, d) => {
      const [state, note] = row.state(day);
      const x = labelWidth + d * (cell + gap);
      const title = `${formatDate(day)}: ${note}`;
      if (state === 'missing') {
        const g = svg('g', { class: 'cell-missing' }, title);
        g.append(svg('rect', { x: x + 0.5, y: y + 0.5, width: cell - 1, height: cell - 1, rx: 3 }));
        g.append(svg('path', { d: `M${x + 5} ${y + 5}L${x + cell - 5} ${y + cell - 5}M${x + cell - 5} ${y + 5}L${x + 5} ${y + cell - 5}` }));
        chart.append(g);
      } else {
        chart.append(svg('rect', { x: x + 0.5, y: y + 0.5, width: cell - 1, height: cell - 1, rx: 3,
          class: state === 'done' ? row.className : `cell-${state}` }, title));
      }
    });
  });

  // A date under every Monday not too close to today, and "Today".
  days.forEach((day, d) => {
    const isToday = day === today;
    const monday = new Date(`${day}T00:00:00Z`).getUTCDay() === 1 && d < CHART_DAYS - 4;
    if (!monday && !isToday) return;
    const x = labelWidth + d * (cell + gap) + (isToday ? cell : cell / 2);
    const tick = svg('text', { x, y: height - 6, class: isToday ? 'chart-tick chart-today' : 'chart-tick',
      'text-anchor': isToday ? 'end' : 'middle' });
    tick.textContent = isToday ? 'Today' : formatDate(day).replace(/, \d{4}$/, '');
    chart.append(tick);
  });
  document.querySelector('[data-coverage]').append(chart);

  const legend = document.querySelector('[data-coverage-legend]');
  for (const [className, text] of [['cell-runs', 'Update ran'], ['cell-imdb', 'IMDb data'],
    ['cell-tmdb', 'TMDB data'], ['cell-wikipedia', 'Wikipedia data'], ['cell-missing', 'Missing'],
    ['cell-pending', 'Not due yet']]) {
    const item = document.createElement('span');
    item.className = 'legend-item';
    const swatch = document.createElement('span');
    swatch.className = `swatch ${className}`;
    item.append(swatch, text);
    legend.append(item);
  }
}

// — Growth chart ————————————————————————————————————————————————————————

function showGrowth(log) {
  const points = [...log].reverse().map((item) => ({ time: new Date(item.time), bytes: item.totals.bytes }));
  if (!points.length) return;
  const width = 1000;
  const height = 220;
  const pad = { left: 56, right: 16, top: 12, bottom: 28 };
  const t0 = points[0].time.getTime();
  const t1 = Math.max(now.getTime(), t0 + DAY_MS);
  // The axis covers the data's range, not from zero, so growth shows.
  const sizes = points.map((p) => p.bytes / 1e6);
  const spread = Math.max(Math.max(...sizes) - Math.min(...sizes), 0.05);
  const step = niceMax(spread / 3);
  const minMB = Math.max(0, Math.floor((Math.min(...sizes) - spread * 0.2) / step) * step);
  const maxMB = Math.ceil((Math.max(...sizes) + spread * 0.2) / step) * step;
  const x = (time) => pad.left + (time - t0) / (t1 - t0) * (width - pad.left - pad.right);
  const y = (mb) => height - pad.bottom - (mb - minMB) / (maxMB - minMB) * (height - pad.top - pad.bottom);

  const chart = svg('svg', { viewBox: `0 0 ${width} ${height}`, class: 'growth', role: 'img',
    'aria-label': `Data in the repository after each update, now ${formatMB(points[points.length - 1].bytes)}` });
  for (let mb = minMB; mb <= maxMB + step / 2; mb += step) {
    chart.append(svg('line', { x1: pad.left, x2: width - pad.right, y1: y(mb), y2: y(mb), class: 'chart-grid' }));
    const label = svg('text', { x: pad.left - 8, y: y(mb), class: 'chart-tick', 'text-anchor': 'end', 'dominant-baseline': 'central' });
    label.textContent = `${mb.toFixed(step < 0.1 ? 2 : 1)} MB`;
    chart.append(label);
  }
  // Steps: the data stays the same between updates.
  let d = '';
  points.forEach((p, i) => {
    const px = x(p.time.getTime());
    d += i === 0 ? `M${px} ${y(p.bytes / 1e6)}` : `H${px}V${y(p.bytes / 1e6)}`;
  });
  d += `H${x(now.getTime())}`;
  chart.append(svg('path', { d, class: 'growth-line' }));
  for (const p of points) {
    chart.append(svg('circle', { cx: x(p.time.getTime()), cy: y(p.bytes / 1e6), r: 4, class: 'growth-point' },
      `${formatTime(p.time)} UTC: ${formatMB(p.bytes)}`));
  }
  const first = svg('text', { x: pad.left, y: height - 6, class: 'chart-tick' });
  first.textContent = formatDate(utcDay(points[0].time)).replace(/, \d{4}$/, '');
  const last = svg('text', { x: width - pad.right, y: height - 6, class: 'chart-tick', 'text-anchor': 'end' });
  last.textContent = 'Now';
  chart.append(first, last);
  document.querySelector('[data-growth]').append(chart);
}

function niceMax(value) {
  const power = 10 ** Math.floor(Math.log10(value || 1));
  for (const step of [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10]) {
    if (value <= step * power) return step * power;
  }
  return 10 * power;
}

// — Totals and the log table ————————————————————————————————————————————

function showTotals({ totals, runs }) {
  const element = document.querySelector('[data-totals]');
  if (!totals) return;
  const cards = Object.keys(NAMES).map((source) => {
    const t = totals[source] || { days: 0 };
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
      cell(text(item.version ? `v${item.version}` : '—')),
      ...Object.keys(NAMES).map((source) => cell(added(item.added[source] || NOTHING, NOUNS[source]))),
      cell(text(item.posters ? `+${item.posters}` : '—')),
      cell(text(formatBytes(item.totals.bytes))),
    );
    if (Object.keys(NAMES).every((source) => !(item.added[source] || NOTHING).days.length)) row.className = 'nothing-new';
    body.append(row);
  }
}

// "Nov 6: 500 movies, 18 KB" (or "Jul 27 to Nov 3 (100 days): …" for a range).
function added({ days, rows, bytes }, noun) {
  if (!days.length) return text('—');
  const short = (day) => formatDate(day).replace(/, \d{4}$/, '');
  const span = days.length === 1 ? short(days[0])
    : `${short(days[0])} to ${short(days[days.length - 1])} (${days.length} days)`;
  return text(`${span}: ${rows.toLocaleString('en-US')} ${noun}, ${formatBytes(bytes)}`);
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

function formatMB(bytes) { return `${(bytes / 1e6).toFixed(2)} MB`; }
