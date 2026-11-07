// TimeScore Demos: renders site/data/movies.json (built daily by
// build/build.py) as top lists at four half-lives and a bar chart race per
// source (movies, or Wikipedia articles), and shows how fresh the data is.

import { EMPTY, addEvent, scoreAt } from './timescore.js?v=__VERSION__';
import { showFreshness, showVersion, formatDate, daysBetween } from './freshness.js?v=__VERSION__';

const DAYS_PER_SECOND = 4;
const RACE_SECONDS = 60;    // a long history plays faster, so a race takes at most about this long
const RACE_SIZE = 10;
const LIST_SHOWN = 20;
const SWITCH_SECONDS = 1;   // how long an item takes to slide to its new rank (like the race)
const BELOW_SHOWN = 3;      // ranks shown fading out below the top list
const OFF_LIST = LIST_SHOWN + BELOW_SHOWN + 2;   // where an item not in the list sits, out of sight
const EASE = 0.2;
const DAY_MS = 86400e3;
const HISTORY_MAX = 8;      // lines on the history chart: one per color in the palette
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
    section.querySelector('[data-history]').remove();
    return section;
  }
  range.textContent = `${source.collected} day${source.collected === 1 ? '' : 's'} of data, `
    + `${formatDate(source.start)} to ${formatDate(source.last)}.`;

  const history = renderHistory(section.querySelector('[data-history]'), source);
  const lists = section.querySelector('[data-lists]');
  lists.append(renderRanking(source, history));
  if (source.collected < data.trendingMinDays) {
    lists.append(renderNotYet(data.trending,
      `Needs ${data.trendingMinDays} days of data, for this week and this month to differ. `
      + `${source.collected} so far.`));
  } else if (source.lists[data.trending]) {
    lists.append(renderList(data.trending, 'This week\'s pace compared with the month\'s (1.0× is steady)',
      source.lists[data.trending], source, (ratio) => `${ratio.toFixed(1)}×`, history));
  }
  renderRace(section.querySelector('[data-race]'), source);
  return section;
}

function renderList(title, note, items, source, format, history) {
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
    const entry = source.items[item.key];
    const li = document.createElement('li');
    const meta = document.createElement('span');
    meta.className = 'list-meta';
    meta.textContent = `${format(item.score)} · ${movement(item.previous, i + 1)}`;
    const rank = document.createElement('span');
    rank.className = 'list-rank';
    rank.textContent = i + 1;
    li.append(rank, image(entry, 'list-poster'), itemBody(entry, meta), history.toggle(item.key));
    ol.append(li);
  });
  list.append(ol);
  return list;
}

// The top items at one half-life, picked with a selector. Switching
// half-lives slides every item to its rank in the new list over
// SWITCH_SECONDS, so the eye can follow it: an item dropping out of the top
// slides down past #20 into a fading zone that shows #21 to #23, and one
// climbing in rises up out of it.
function renderRanking(source, history) {
  const section = document.createElement('section');
  section.className = 'list ranking';
  const heading = document.createElement('h3');
  heading.textContent = `Top ${source.noun}`;
  // Wikipedia's topics: All, People, Politics… each with its own lists.
  const topics = source.topics ? [{ id: 'all', label: 'All' }, ...source.topics] : [];
  const listsFor = (topic) => (topic === 'all' ? source.lists : source.topicLists[topic]);
  const topicBar = document.createElement('div');
  topicBar.className = 'topics';
  topicBar.setAttribute('role', 'group');
  topicBar.setAttribute('aria-label', 'Topic');
  let topic = 'all';
  let halfLife = 'Week';
  const topicButtons = topics.map(({ id, label }) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.dataset.topic = id;
    button.addEventListener('click', () => { topic = id; show(halfLife, true); });
    topicBar.append(button);
    return button;
  });
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
  section.append(heading, ...(topics.length ? [topicBar] : []), selector, note, board, spoken);

  for (let i = 1; i <= LIST_SHOWN; i++) {
    const rank = document.createElement('span');
    rank.className = 'list-rank';
    rank.style.setProperty('--rank', i - 1);
    rank.textContent = i;
    board.append(rank);
  }

  // One card for every item in any of the half-lives' top lists (of any topic).
  const keys = new Set(topics.length ? [] : data.halfLives.flatMap(({ label }) =>
    source.lists[label].slice(0, LIST_SHOWN + BELOW_SHOWN).map((item) => item.key)));
  for (const { id } of topics) {
    for (const { label } of data.halfLives) {
      for (const item of listsFor(id)[label].slice(0, LIST_SHOWN + BELOW_SHOWN)) keys.add(item.key);
    }
  }
  const cards = new Map([...keys].map((key) => {
    const entry = source.items[key];
    const card = document.createElement('div');
    card.className = 'ranking-card';
    card.style.setProperty('--rank', OFF_LIST);
    const meta = document.createElement('span');
    meta.className = 'list-meta';
    const body = itemBody(entry, meta);
    body.querySelectorAll('a').forEach((a) => { a.tabIndex = -1; });
    card.append(image(entry, 'list-poster', -1), body, history.toggle(key, -1));
    board.append(card);
    return [key, { card, meta, shown: false, value: 0, target: 0, previous: null, rank: OFF_LIST }];
  }));

  const buttons = data.halfLives.map(({ label }) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.textContent = label;
    button.addEventListener('click', () => { halfLife = label; show(label, true); });
    selector.append(button);
    return button;
  });

  let tween = 0;
  function show(label, animate) {
    const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
    const moving = animate && !reduced;
    board.classList.toggle('moving', moving);
    buttons.forEach((button) => button.setAttribute('aria-pressed', String(button.textContent === label)));
    topicButtons.forEach((button) => button.setAttribute('aria-pressed', String(button.dataset.topic === topic)));
    history.setHalfLife(label);
    note.textContent = `Each day's activity counts in full, then fades by half every ${label.toLowerCase()}. `
      + 'Press History beside any of them to chart it day by day.';
    const all = listsFor(topic)[label];
    const items = all.slice(0, LIST_SHOWN);
    const ranks = new Map(all.map((item, i) => [item.key, i]));

    // Every card moves to its rank in the new list; an item that isn't in
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
      li.append(`${source.items[item.key].title}, ${formatScore(item.score)} `, history.toggle(item.key));
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

// An item's title (a link), its short description when it has one (Wikipedia
// articles), and its meta line.
function itemBody(entry, meta) {
  const body = document.createElement('span');
  body.className = 'list-body';
  const title = document.createElement('a');
  title.className = 'list-title';
  title.href = entry.link;
  title.textContent = entry.title;
  body.append(title);
  if (entry.description) {
    body.classList.add('has-description');
    title.title = `${entry.title}: ${entry.description}`;
    const description = document.createElement('span');
    description.className = 'list-description';
    description.textContent = entry.description;
    body.append(description);
  }
  body.append(meta);
  return body;
}

// An item's poster or picture, or a gray box when it has none. A Wikipedia
// image links to its page on Wikimedia Commons and names its author and
// license, as its license asks.
function image(entry, className, tabIndex) {
  if (!entry.image) {
    const blank = document.createElement('span');
    blank.className = `${className} no-poster`;
    blank.setAttribute('aria-hidden', 'true');
    return blank;
  }
  const img = document.createElement('img');
  img.className = className;
  img.src = entry.image;
  img.alt = '';
  img.loading = 'lazy';
  if (!entry.imagePage) return img;
  const link = document.createElement('a');
  link.className = 'image-credit';
  link.href = entry.imagePage;
  link.title = `Image: ${entry.imageCredit || 'see its page for author and license'}`;
  link.setAttribute('aria-label', link.title);
  if (tabIndex !== undefined) link.tabIndex = tabIndex;
  link.append(img);
  return link;
}

// An item's TimeScore at the end of each day, from its daily values
// ([[day, value], …]), for a half-life in days.
function dailyScores(points, days, halfLife) {
  const events = new Map(points);
  let logScore = EMPTY;
  const daily = new Float64Array(days);
  for (let d = 0; d < days; d++) {
    if (events.get(d) > 0) logScore = addEvent(logScore, events.get(d), d, halfLife);
    daily[d] = logScore === EMPTY ? 0 : scoreAt(logScore, d, halfLife);
  }
  return daily;
}

// — History: chosen items' scores over the whole history ————————————————————

// The race's data drawn as lines: each chosen item's TimeScore on every day,
// at the half-life chosen for the top list. Items are chosen with the chart
// toggle beside each one (at most HISTORY_MAX); each keeps its color until
// it is removed.
function renderHistory(figure, source) {
  const days = daysBetween(source.start, source.last) + 1;
  const chosen = new Map();   // key → color slot (0–7), in the order chosen
  const toggles = new Map();  // key → [buttons]
  let halfLife = 'Week';
  const legend = figure.querySelector('[data-history-legend]');
  const plot = figure.querySelector('[data-history-plot]');
  const note = figure.querySelector('[data-history-note]');
  figure.querySelector('[data-history-clear]').addEventListener('click', () => {
    chosen.clear();
    update();
  });

  function toggle(key, tabIndex) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'history-toggle';
    button.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M1.5 12.5 6 8l3 3 5.5-6.5"/></svg>'
      + '<span class="history-toggle-label">History</span>';
    if (tabIndex !== undefined) button.tabIndex = tabIndex;
    button.addEventListener('click', (event) => {
      event.preventDefault();
      if (chosen.has(key)) chosen.delete(key);
      else if (chosen.size < HISTORY_MAX) {
        const used = new Set(chosen.values());
        chosen.set(key, [...Array(HISTORY_MAX).keys()].find((slot) => !used.has(slot)));
      }
      update();
    });
    if (!toggles.has(key)) toggles.set(key, []);
    toggles.get(key).push(button);
    paint(key, button);
    return button;
  }

  function paint(key, button) {
    const on = chosen.has(key);
    const title = source.items[key]?.title || '';
    button.setAttribute('aria-pressed', String(on));
    button.style.setProperty('--pick', on ? `var(--series-${chosen.get(key) + 1})` : '');
    button.dataset.slot = on ? chosen.get(key) + 1 : '';
    button.disabled = !on && chosen.size >= HISTORY_MAX;
    button.title = on ? `Remove ${title} from the history chart`
      : button.disabled ? `The history chart shows at most ${HISTORY_MAX}` : `Show ${title}'s history`;
    button.setAttribute('aria-label', button.title);
  }

  function update() {
    // The screen-reader list is rebuilt on every switch: forget its old buttons.
    for (const [key, buttons] of toggles) toggles.set(key, buttons.filter((b) => b.isConnected));
    for (const [key, buttons] of toggles) for (const button of buttons) paint(key, button);
    figure.hidden = chosen.size === 0;
    if (!chosen.size) return;
    const halfLifeDays = data.halfLives.find((h) => h.label === halfLife).days;
    note.textContent = `Each day's TimeScore with a half-life of a ${halfLife.toLowerCase()}, `
      + `${formatDate(source.start)} to ${formatDate(source.last)}.`;
    const lines = [...chosen].map(([key, slot]) => ({
      key, slot, title: source.items[key].title, daily: dailyScores(source.series[key] || [], days, halfLifeDays),
    }));
    legend.replaceChildren(...lines.map(({ key, slot, title }) => {
      const item = document.createElement('span');
      item.className = 'legend-item';
      const swatch = document.createElement('span');
      swatch.className = 'swatch';
      swatch.style.background = `var(--series-${slot + 1})`;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'legend-remove';
      remove.textContent = '×';
      remove.setAttribute('aria-label', `Remove ${title}`);
      remove.addEventListener('click', () => { chosen.delete(key); update(); });
      item.append(swatch, title, remove);
      return item;
    }));
    drawHistory(plot, lines, source.start, days);
    drawn = lines;
  }
  // Redraw at the new width when the window is resized.
  let drawn = null;
  let lastWidth = 0;
  new ResizeObserver(() => {
    const width = plot.clientWidth;
    if (drawn && !figure.hidden && width && Math.abs(width - lastWidth) > 4) {
      lastWidth = width;
      drawHistory(plot, drawn, source.start, days);
    }
  }).observe(plot);

  return {
    toggle,
    setHalfLife(label) {
      if (label === halfLife) return;
      halfLife = label;
      if (chosen.size) update();
    },
  };
}

// The history chart: one line per item, a date axis, a score axis from zero,
// and a crosshair that reads out every line's score on the day under it.
function drawHistory(plot, lines, start, days) {
  // Drawn at the panel's own width, so the text stays readable on a phone.
  const width = Math.max(280, Math.round(plot.clientWidth || 1000));
  const height = width < 600 ? 220 : 300;
  const pad = { left: width < 600 ? 44 : 64, right: 12, top: 12, bottom: 28 };
  const max = Math.max(...lines.map((l) => Math.max(...l.daily)), 1e-9);
  const step = niceStep(max / 4);
  const top = Math.ceil(max / step) * step;
  const x = (d) => pad.left + (days > 1 ? d / (days - 1) : 0.5) * (width - pad.left - pad.right);
  const y = (v) => height - pad.bottom - (v / top) * (height - pad.top - pad.bottom);
  const chart = svgElement('svg', { viewBox: `0 0 ${width} ${height}`, class: 'history-chart', role: 'img',
    'aria-label': `TimeScore by day for ${lines.map((l) => l.title).join(', ')}` });
  for (let v = 0; v <= top + step / 2; v += step) {
    chart.append(svgElement('line', { x1: pad.left, x2: width - pad.right, y1: y(v), y2: y(v),
      class: v === 0 ? 'history-axis' : 'history-grid' }));
    const label = svgElement('text', { x: pad.left - 8, y: y(v), class: 'history-tick', 'text-anchor': 'end',
      'dominant-baseline': 'central' });
    label.textContent = formatCompact(v);
    chart.append(label);
  }
  // A date under the first day of each month (every few months for a long history).
  const months = [];
  for (let d = 0; d < days; d++) if (addDays(start, d).endsWith('-01')) months.push(d);
  const every = Math.max(1, Math.ceil(months.length / Math.max(2, Math.floor(width / 110))));
  months.filter((_, i) => i % every === 0).forEach((d) => {
    const label = svgElement('text', { x: x(d), y: height - 8, class: 'history-tick', 'text-anchor': 'middle' });
    const date = new Date(`${addDays(start, d)}T00:00:00Z`);
    label.textContent = date.toLocaleDateString('en-US', { month: 'short', timeZone: 'UTC' })
      + (date.getUTCMonth() === 0 || d === months[0] ? ` ${date.getUTCFullYear()}` : '');
    chart.append(label);
  });
  for (const line of lines) {
    let path = '';
    line.daily.forEach((v, d) => { path += `${d ? 'L' : 'M'}${x(d).toFixed(1)} ${y(v).toFixed(1)}`; });
    chart.append(svgElement('path', { d: path, class: 'history-line', style: `stroke: var(--series-${line.slot + 1})` }));
  }
  const cross = svgElement('line', { y1: pad.top, y2: height - pad.bottom, class: 'history-cross', visibility: 'hidden' });
  const dots = lines.map((line) => svgElement('circle', { r: 4.5, class: 'history-dot',
    style: `fill: var(--series-${line.slot + 1})`, visibility: 'hidden' }));
  chart.append(cross, ...dots);
  const hit = svgElement('rect', { x: pad.left, y: 0, width: width - pad.left - pad.right, height, class: 'history-hit' });
  chart.append(hit);

  const tip = document.createElement('div');
  tip.className = 'history-tip';
  tip.hidden = true;
  function point(event) {
    const box = chart.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * width;
    const d = Math.max(0, Math.min(days - 1, Math.round(((px - pad.left) / (width - pad.left - pad.right)) * (days - 1))));
    cross.setAttribute('x1', x(d));
    cross.setAttribute('x2', x(d));
    cross.setAttribute('visibility', 'visible');
    lines.forEach((line, i) => {
      dots[i].setAttribute('cx', x(d));
      dots[i].setAttribute('cy', y(line.daily[d]));
      dots[i].setAttribute('visibility', 'visible');
    });
    tip.replaceChildren();
    const date = document.createElement('strong');
    date.textContent = formatDate(addDays(start, d));
    tip.append(date);
    for (const line of [...lines].sort((a, b) => b.daily[d] - a.daily[d])) {
      const row = document.createElement('span');
      row.className = 'history-tip-row';
      const swatch = document.createElement('span');
      swatch.className = 'swatch';
      swatch.style.background = `var(--series-${line.slot + 1})`;
      const value = document.createElement('span');
      value.className = 'history-tip-value';
      value.textContent = formatScore(line.daily[d]);
      row.append(swatch, line.title, value);
      tip.append(row);
    }
    tip.hidden = false;
    const left = (x(d) / width) * box.width;
    tip.style.left = `${Math.min(left + 12, box.width - tip.offsetWidth - 4)}px`;
    if (left + 12 + tip.offsetWidth > box.width) tip.style.left = `${Math.max(0, left - tip.offsetWidth - 12)}px`;
  }
  function hide() {
    cross.setAttribute('visibility', 'hidden');
    dots.forEach((dot) => dot.setAttribute('visibility', 'hidden'));
    tip.hidden = true;
  }
  hit.addEventListener('pointermove', point);
  hit.addEventListener('pointerdown', point);
  hit.addEventListener('pointerleave', hide);
  plot.replaceChildren(chart, tip);
}

function svgElement(tag, attrs) {
  const element = document.createElementNS('http://www.w3.org/2000/svg', tag);
  for (const [key, value] of Object.entries(attrs)) element.setAttribute(key, value);
  return element;
}

function niceStep(value) {
  const power = 10 ** Math.floor(Math.log10(value || 1));
  for (const step of [1, 2, 2.5, 5, 10]) if (value <= step * power) return step * power;
  return 10 * power;
}

function formatCompact(value) {
  return value === 0 ? '0' : value.toLocaleString('en-US', { notation: 'compact', maximumFractionDigits: 1 });
}

// — The race ————————————————————————————————————————————————————————————

function renderRace(figure, source) {
  const days = daysBetween(source.start, source.last) + 1;
  const keys = source.racers;
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
    const entry = source.items[key];
    const bar = document.createElement('div');
    bar.className = 'race-bar';
    bar.innerHTML = '<span class="race-label"></span><span class="race-track"><span class="race-fill"></span><span class="race-value"></span></span>';
    bar.prepend(image(entry, 'race-poster', -1));
    bar.querySelector('.race-label').textContent = entry.title;
    barsElement.append(bar);
    return [key, { bar, fill: bar.querySelector('.race-fill'), value: bar.querySelector('.race-value'), y: RACE_SIZE }];
  }));

  // Each racer's TimeScore at the end of each day, for a half-life in days.
  let values;
  function score(halfLife) {
    values = new Map(keys.map((key) => [key, dailyScores(source.series[key], days, halfLife)]));
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
      if (seconds < 0.25) position += seconds * Math.max(DAYS_PER_SECOND, days / RACE_SECONDS);
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
