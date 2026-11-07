// TimeScore Movie Charts: renders site/data/movies.json (built daily by
// build/build.py) as top lists at four half-lives and a bar chart race per
// source, and shows how fresh the data is.

import { EMPTY, addEvent, scoreAt } from './timescore.js?v=__VERSION__';
import { showFreshness, formatDate, daysBetween } from './freshness.js?v=__VERSION__';

const DAYS_PER_SECOND = 4;
const RACE_SIZE = 10;
const LIST_SHOWN = 10;
const EASE = 0.2;
const DAY_MS = 86400e3;

const data = await fetch(`data/movies.json?v=${Date.now()}`).then((r) => r.json());
showFreshness(data);
addLogLink();
const main = document.querySelector('[data-sources]');
for (const [id, source] of Object.entries(data.sources)) main.append(renderSource(id, source));

// — A source: four lists and a race ———————————————————————————————————

function renderSource(id, source) {
  const section = document.getElementById('source-template').content.firstElementChild.cloneNode(true);
  section.querySelector('[data-name]').textContent = source.name;
  section.querySelector('[data-about]').textContent = source.about;
  const range = section.querySelector('[data-range]');
  if (!source.collected) {
    range.textContent = 'Collecting started. The first lists appear after the second daily update.';
    section.querySelector('[data-race]').remove();
    return section;
  }
  range.textContent = `${source.collected} day${source.collected === 1 ? '' : 's'} of data, `
    + `${formatDate(source.start)} to ${formatDate(source.last)}.`;

  const lists = section.querySelector('[data-lists]');
  for (const { label } of data.halfLives) {
    lists.append(renderList(`${label} half-life`, null, source.lists[label], source, formatScore));
  }
  if (source.collected < data.trendingMinDays) {
    lists.append(renderNotYet(data.trending,
      `Needs ${data.trendingMinDays} days of data, for this week and this month to differ. `
      + `${source.collected} so far.`));
  } else if (source.lists[data.trending]) {
    lists.append(renderList(data.trending, 'This week\'s pace compared with the month\'s (1.0× is steady)',
      source.lists[data.trending], source, (ratio) => `${ratio.toFixed(1)}×`));
  }
  renderRace(section.querySelector('[data-race]'), source);
  return section;
}

function renderList(title, note, items, source, format) {
  const list = document.createElement('section');
  list.className = 'list';
  const heading = document.createElement('h3');
  heading.textContent = title;
  list.append(heading);
  if (note) {
    const p = document.createElement('p');
    p.className = 'list-note';
    p.textContent = note;
    list.append(p);
  }
  const ol = document.createElement('ol');
  items.slice(0, LIST_SHOWN).forEach((item, i) => {
    const movie = source.movies[item.key];
    const li = document.createElement('li');
    li.append(poster(movie, 'list-poster'));
    const text = document.createElement('a');
    text.className = 'list-title';
    text.href = movie.link;
    text.textContent = movie.title;
    const meta = document.createElement('span');
    meta.className = 'list-meta';
    meta.textContent = `${format(item.score)} · ${movement(item.previous, i + 1)}`;
    const rank = document.createElement('span');
    rank.className = 'list-rank';
    rank.textContent = i + 1;
    const body = document.createElement('span');
    body.className = 'list-body';
    body.append(text, meta);
    li.append(rank, body);
    li.prepend(rank);
    ol.append(li);
  });
  list.append(ol);
  return list;
}

function renderNotYet(title, message) {
  const list = document.createElement('section');
  list.className = 'list';
  const heading = document.createElement('h3');
  heading.textContent = title;
  const p = document.createElement('p');
  p.className = 'list-note';
  p.textContent = message;
  list.append(heading, p);
  return list;
}

function movement(previous, rank) {
  if (previous === null || previous === undefined) return 'new';
  if (previous === rank) return 'same';
  return previous > rank ? `▲ ${previous - rank}` : `▼ ${rank - previous}`;
}

function poster(movie, className) {
  if (!movie.poster) {
    const blank = document.createElement('span');
    blank.className = `${className} no-poster`;
    blank.setAttribute('aria-hidden', 'true');
    return blank;
  }
  const img = document.createElement('img');
  img.className = className;
  img.src = movie.poster;
  img.alt = '';
  img.loading = 'lazy';
  return img;
}

// — The race ————————————————————————————————————————————————————————————

function renderRace(figure, source) {
  const days = daysBetween(source.start, source.last) + 1;
  const keys = Object.keys(source.race);
  const select = figure.querySelector('[data-half-life]');
  for (const { label, days: halfLife } of data.halfLives) {
    select.append(new Option(`${label}`, halfLife, false, label === 'Week'));
  }
  const scrubber = figure.querySelector('[data-scrubber]');
  scrubber.max = days - 1;
  const dateLabel = figure.querySelector('[data-date]');
  const playButton = figure.querySelector('[data-play]');
  const barsElement = figure.querySelector('[data-bars]');

  const bars = new Map(keys.map((key) => {
    const movie = source.movies[key];
    const bar = document.createElement('div');
    bar.className = 'race-bar';
    bar.innerHTML = '<span class="race-label"></span><span class="race-track"><span class="race-fill"></span><span class="race-value"></span></span>';
    bar.prepend(poster(movie, 'race-poster'));
    bar.querySelector('.race-label').textContent = movie.title;
    barsElement.append(bar);
    return [key, { bar, fill: bar.querySelector('.race-fill'), value: bar.querySelector('.race-value'), y: RACE_SIZE }];
  }));

  // Each racer's TimeScore at the end of each day, for a half-life in days.
  let values;
  function score(halfLife) {
    values = new Map(keys.map((key) => {
      const events = new Map(source.race[key]);
      let logScore = EMPTY;
      const daily = new Float64Array(days);
      for (let d = 0; d < days; d++) {
        if (events.get(d) > 0) logScore = addEvent(logScore, events.get(d), d, halfLife);
        daily[d] = logScore === EMPTY ? 0 : scoreAt(logScore, d, halfLife);
      }
      return [key, daily];
    }));
  }
  score(Number(select.value));

  let position = days - 1;   // start at the latest day
  let running = false;
  let lastFrame = null;
  let snap = true;

  select.addEventListener('change', () => { score(Number(select.value)); draw(); });
  scrubber.addEventListener('input', () => { position = Number(scrubber.value); running = false; draw(); });
  playButton.addEventListener('click', () => {
    if (!running && position >= days - 1) position = 0;
    running = !running;
    lastFrame = null;
    draw();
  });

  function valueAt(daily, at) {
    const d = Math.min(Math.floor(at), days - 1);
    const next = Math.min(d + 1, days - 1);
    return daily[d] + (daily[next] - daily[d]) * (at - d);
  }

  function draw() {
    const day = Math.min(Math.floor(position), days - 1);
    dateLabel.textContent = formatDate(addDays(source.start, day));
    scrubber.value = day;
    playButton.textContent = running ? 'Pause' : 'Play';
    playButton.setAttribute('aria-pressed', String(!running));
    const now = keys.map((key) => [valueAt(values.get(key), position), key]).sort((a, b) => b[0] - a[0]);
    const max = Math.max(now[0]?.[0] || 0, 1e-9);
    now.forEach(([value, key], rank) => {
      const b = bars.get(key);
      const shown = rank < RACE_SIZE && value > 0;
      const target = shown ? rank : RACE_SIZE;
      b.y = snap ? target : b.y + (target - b.y) * EASE;
      b.bar.style.transform = `translateY(calc(${b.y.toFixed(3)} * var(--race-row)))`;
      b.bar.classList.toggle('hidden', !shown);
      b.fill.style.width = `${(value / max) * 100}%`;
      b.value.textContent = formatScore(value);
    });
    snap = false;
  }

  function frame(timestamp) {
    if (running && lastFrame !== null) {
      const seconds = (timestamp - lastFrame) / 1000;
      if (seconds < 0.25) position += seconds * DAYS_PER_SECOND;
      if (position >= days - 1) { position = days - 1; running = false; }
    }
    lastFrame = timestamp;
    draw();
    requestAnimationFrame(frame);
  }
  draw();
  requestAnimationFrame(frame);
}

// — Formatting ——————————————————————————————————————————————————————————

function addDays(date, n) { return new Date(Date.parse(date) + n * DAY_MS).toISOString().slice(0, 10); }
function formatScore(value) {
  return value >= 100 ? Math.round(value).toLocaleString('en-US') : value.toFixed(1);
}

// A link to the update log, after the freshness line.
function addLogLink() {
  const link = document.createElement('a');
  link.href = 'status.html';
  link.textContent = 'Update log';
  document.querySelector('[data-freshness]').append(' · ', link);
}
