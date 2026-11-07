// TimeScore Movie Charts: renders site/data/movies.json (built daily by
// build/build.py) as top lists at four half-lives and a bar chart race per
// source, and shows how fresh the data is.

import { EMPTY, addEvent, scoreAt } from './timescore.js?v=__VERSION__';
import { showFreshness, showVersion, formatDate, daysBetween } from './freshness.js?v=__VERSION__';

const DAYS_PER_SECOND = 4;
const RACE_SIZE = 10;
const LIST_SHOWN = 10;
const SWITCH_SECONDS = 1;   // how long a movie takes to slide to its new rank (like the race)
const BELOW_SHOWN = 3;      // ranks shown fading out below the top list
const OFF_LIST = LIST_SHOWN + BELOW_SHOWN + 2;   // where a movie not in the list sits, out of sight
const EASE = 0.2;
const DAY_MS = 86400e3;
const DEFAULT_SOURCE = 'tmdb';   // the source with the most history

const data = await fetch(`data/movies.json?v=${Date.now()}`).then((r) => r.json());
showFreshness(data);
showVersion(data.version);
addLogLink();
const main = document.querySelector('[data-sources]');
showSources(data.sources);

// — Tabs: one source at a time ————————————————————————————————————————————

// A tab for each source, with how many days of data it has, and its section
// below; the chosen source is in the URL (#tmdb), TMDB by default since it
// has the most history.
function showSources(sources) {
  const tabs = document.querySelector('[data-tabs]');
  const order = Object.keys(sources).sort((a, b) => (a === DEFAULT_SOURCE ? -1 : b === DEFAULT_SOURCE ? 1 : 0));
  const panels = new Map();
  const buttons = new Map();
  for (const id of order) {
    const source = sources[id];
    const button = document.createElement('button');
    button.type = 'button';
    button.id = `tab-${id}`;
    button.setAttribute('role', 'tab');
    button.setAttribute('aria-controls', `source-${id}`);
    const name = document.createElement('span');
    name.className = 'tab-name';
    name.textContent = source.name;
    const days = document.createElement('span');
    days.className = 'tab-days';
    days.textContent = source.collected
      ? `${source.collected} day${source.collected === 1 ? '' : 's'} of data` : 'Collecting';
    button.append(name, days);
    button.addEventListener('click', () => {
      history.replaceState(null, '', `#${id}`);
      select(id);
    });
    tabs.append(button);
    buttons.set(id, button);
    const panel = renderSource(id, source);
    panel.id = `source-${id}`;
    panel.setAttribute('role', 'tabpanel');
    panel.setAttribute('aria-labelledby', `tab-${id}`);
    main.append(panel);
    panels.set(id, panel);
  }
  // Arrow keys move between tabs.
  tabs.addEventListener('keydown', (event) => {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
    if (!step) return;
    const i = order.indexOf(document.activeElement.id.replace('tab-', ''));
    const next = order[(i + step + order.length) % order.length];
    buttons.get(next).focus();
    buttons.get(next).click();
  });
  function select(id) {
    if (!panels.has(id)) id = DEFAULT_SOURCE;
    for (const [key, button] of buttons) {
      button.setAttribute('aria-selected', String(key === id));
      button.tabIndex = key === id ? 0 : -1;
      panels.get(key).hidden = key !== id;
    }
  }
  select(location.hash.slice(1));
  window.addEventListener('hashchange', () => select(location.hash.slice(1)));
}

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
  lists.append(renderRanking(source));
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

// The top movies at one half-life, picked with a selector. Switching
// half-lives slides every movie to its rank in the new list over
// SWITCH_SECONDS, so the eye can follow it: a movie dropping out of the top
// slides down past #10 into a fading zone that shows #11 to #13, and one
// climbing in rises up out of it.
function renderRanking(source) {
  const section = document.createElement('section');
  section.className = 'list ranking';
  const heading = document.createElement('h3');
  heading.textContent = 'Top movies';
  const selector = document.createElement('div');
  selector.className = 'half-lives';
  selector.setAttribute('role', 'group');
  selector.setAttribute('aria-label', 'Half-life');
  const note = document.createElement('p');
  note.className = 'list-note';
  const board = document.createElement('div');
  board.className = 'ranking-board';
  board.setAttribute('aria-hidden', 'true');
  board.style.setProperty('--rows', LIST_SHOWN);
  const spoken = document.createElement('ol');
  spoken.className = 'visually-hidden';
  spoken.setAttribute('aria-live', 'polite');
  section.append(heading, selector, note, board, spoken);

  for (let i = 1; i <= LIST_SHOWN; i++) {
    const rank = document.createElement('span');
    rank.className = 'list-rank';
    rank.style.setProperty('--rank', i - 1);
    rank.textContent = i;
    board.append(rank);
  }

  // One card for every movie in any of the half-lives' top lists.
  const keys = new Set(data.halfLives.flatMap(({ label }) =>
    source.lists[label].slice(0, LIST_SHOWN + BELOW_SHOWN).map((item) => item.key)));
  const cards = new Map([...keys].map((key) => {
    const movie = source.movies[key];
    const card = document.createElement('div');
    card.className = 'ranking-card';
    card.style.setProperty('--rank', OFF_LIST);
    const title = document.createElement('a');
    title.className = 'list-title';
    title.href = movie.link;
    title.tabIndex = -1;
    title.textContent = movie.title;
    const meta = document.createElement('span');
    meta.className = 'list-meta';
    const body = document.createElement('span');
    body.className = 'list-body';
    body.append(title, meta);
    card.append(poster(movie, 'list-poster'), body);
    board.append(card);
    return [key, { card, meta, shown: false, value: 0, target: 0, previous: null, rank: OFF_LIST }];
  }));

  const buttons = data.halfLives.map(({ label }) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.addEventListener('click', () => show(label, true));
    selector.append(button);
    return button;
  });

  let tween = 0;
  function show(label, animate) {
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const moving = animate && !reduced;
    board.classList.toggle('moving', moving);
    buttons.forEach((button) => button.setAttribute('aria-pressed', String(button.textContent === label)));
    note.textContent = `Each day's activity counts in full, then fades by half every ${label.toLowerCase()}.`;
    const all = source.lists[label];
    const items = all.slice(0, LIST_SHOWN);
    const ranks = new Map(all.map((item, i) => [item.key, i]));

    // Every card moves to its rank in the new list; a movie that isn't in
    // it at all goes below the visible zone.
    const from = new Map();
    for (const [key, c] of cards) {
      const rank = ranks.has(key) ? ranks.get(key) : OFF_LIST;
      from.set(key, c.value);
      c.card.style.setProperty('--rank', rank);
      c.shown = rank < LIST_SHOWN;
      c.card.classList.toggle('shown', c.shown);
      c.rank = rank;
      if (ranks.has(key)) {
        c.target = all[rank].score;
        c.previous = all[rank].previous;
      }
    }

    // Count each score to its new value over the same time as the slide.
    cancelAnimationFrame(tween);
    const start = performance.now();
    const step = (now) => {
      const t = moving ? Math.min(1, (now - start) / (SWITCH_SECONDS * 1000)) : 1;
      const eased = t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2;
      for (const [key, c] of cards) {
        if (c.rank === OFF_LIST) continue;
        c.value = from.get(key) + (c.target - from.get(key)) * eased;
        c.meta.textContent = `${formatScore(c.value)} · ${movement(c.previous, c.rank + 1)}`;
      }
      if (t < 1) tween = requestAnimationFrame(step);
      else board.classList.remove('moving');
    };
    tween = requestAnimationFrame(step);

    spoken.replaceChildren(...items.map((item) => {
      const li = document.createElement('li');
      li.textContent = `${source.movies[item.key].title}, ${formatScore(item.score)}`;
      return li;
    }));
  }
  show('Week', false);
  return section;
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
