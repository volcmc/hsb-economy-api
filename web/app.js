"use strict";

// Resolve against the page so the explorer works both on GitHub Pages and from a local ./site build.
const API = new URL("v1/", document.baseURI);
const SVG_NS = "http://www.w3.org/2000/svg";
const HOUR = 3600;
const DAY = 86400;
const STALE_AFTER_SECONDS = 2 * HOUR;
const MAX_RESULTS = 20;

const SERIES = {
  bazaar: [
    { metric: "buy", label: "Instant buy", color: "--series-1" },
    { metric: "sell", label: "Instant sell", color: "--series-2" },
  ],
  auctions: [{ metric: "lbin", label: "Lowest BIN", color: "--series-1" }],
};
const RESOLUTION = { hourly: HOUR, daily: DAY };

const state = {
  items: [],
  bazaar: {},
  auctions: {},
  historyCache: new Map(),
  current: null,
  range: "hourly",
  activeResult: -1,
  results: [],
};

const $ = (id) => document.getElementById(id);

/* ---------- formatting ---------- */

const compactFormat = new Intl.NumberFormat("en", { notation: "compact", maximumSignificantDigits: 3 });
const fullFormat = new Intl.NumberFormat("en", { maximumFractionDigits: 2 });
const percentFormat = new Intl.NumberFormat("en", { style: "percent", maximumFractionDigits: 1, signDisplay: "exceptZero" });

function coins(value) {
  if (value === null || value === undefined) return "—";
  return Math.abs(value) < 10_000 ? fullFormat.format(value) : compactFormat.format(value);
}

function count(value) {
  if (value === null || value === undefined) return "—";
  return Math.abs(value) < 10_000 ? fullFormat.format(Math.round(value)) : compactFormat.format(value);
}

function change(value) {
  if (value === null || value === undefined) return "—";
  const arrow = value > 0 ? "▲ " : value < 0 ? "▼ " : "";
  return arrow + percentFormat.format(value);
}

function trendNote(day, week) {
  if ((day ?? null) === null && (week ?? null) === null) return "Trend after a day of history";
  return `24h ${change(day)} · 7d ${change(week)}`;
}

function ago(seconds) {
  if (seconds < 90) return "just now";
  if (seconds < 90 * 60) return `${Math.round(seconds / 60)} min ago`;
  if (seconds < 36 * HOUR) return `${Math.round(seconds / HOUR)} h ago`;
  return `${Math.round(seconds / DAY)} days ago`;
}

const dateTimeFormat = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
const dateFormat = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" });

function formatTime(seconds, resolution) {
  return (resolution >= DAY ? dateFormat : dateTimeFormat).format(new Date(seconds * 1000));
}

/* ---------- data ---------- */

async function getJSON(path) {
  const response = await fetch(new URL(path, API));
  if (!response.ok) throw new Error(`${path} returned HTTP ${response.status}`);
  return response.json();
}

function buildIndex() {
  const items = [];
  for (const [key, product] of Object.entries(state.bazaar)) {
    const price = product.buy ?? product.sell;
    const dailyVolume = (product.buy_moving_week + product.sell_moving_week) / 7;
    items.push(indexEntry("bazaar", key, product.name, price, dailyVolume * (price ?? 0)));
  }
  for (const [key, item] of Object.entries(state.auctions)) {
    const sales = item.sales;
    const perDay = sales ? (sales.est_volume_1d ?? sales.count_7d / 7) : 0;
    const salePrice = sales?.median_7d ?? item.lbin ?? 0;
    // Listings break ties for items with no recorded sales.
    items.push(indexEntry("auctions", key, item.name, item.lbin ?? item.last_seen?.lbin, perDay * salePrice + item.listings));
  }
  items.sort((a, b) => b.activity - a.activity);
  state.items = items;
}

function indexEntry(source, key, name = key, price, activity) {
  return { source, key, name, price, activity, haystack: `${name} ${key}`.toLowerCase().replaceAll("_", " ") };
}

/* ---------- status ---------- */

function renderStatus(meta) {
  const status = $("status");
  status.replaceChildren();
  const age = Date.now() / 1000 - meta.generated_at;
  const fresh = age < STALE_AFTER_SECONDS;
  const dot = document.createElement("span");
  dot.className = `status-dot ${fresh ? "good" : "warning"}`;
  dot.setAttribute("aria-hidden", "true");
  const coverage = percentFormat.format(meta.sales_coverage_1d).replace("+", "");
  const text = document.createElement("span");
  text.textContent =
    `${fresh ? "Live" : "Delayed"} · updated ${ago(age)} · ` +
    `${count(meta.counts.auction_items)} auction items · ${count(meta.counts.bazaar_products)} bazaar products · ` +
    `${coverage} of the last day's sales recorded`;
  status.append(dot, text);
}

function renderError(error) {
  const status = $("status");
  const dot = document.createElement("span");
  dot.className = "status-dot warning";
  dot.setAttribute("aria-hidden", "true");
  const text = document.createElement("span");
  text.textContent = `Couldn't load data (${error.message}). Try again shortly.`;
  status.replaceChildren(dot, text);
}

/* ---------- search ---------- */

function search(query) {
  const tokens = query.toLowerCase().replaceAll("_", " ").split(/\s+/).filter(Boolean);
  if (!tokens.length) return [];
  const phrase = tokens.join(" ");
  const scored = [];
  for (const item of state.items) {
    if (!tokens.every((token) => item.haystack.includes(token))) continue;
    const name = item.name.toLowerCase();
    const score =
      name === phrase || item.key.toLowerCase() === phrase ? 4
      : name.startsWith(phrase) ? 3
      : name.includes(` ${phrase}`) || item.haystack.startsWith(phrase) ? 2
      : 1;
    scored.push({ item, score });
    if (scored.length > 2000) break;
  }
  // state.items is already ordered by activity, and sort is stable.
  scored.sort((a, b) => b.score - a.score);
  return scored.slice(0, MAX_RESULTS).map((entry) => entry.item);
}

function renderResults() {
  const list = $("search-results");
  const input = $("search-input");
  list.replaceChildren();
  state.results.forEach((item, index) => {
    const option = document.createElement("li");
    option.id = `result-${index}`;
    option.setAttribute("role", "option");
    option.setAttribute("aria-selected", String(index === state.activeResult));
    const name = document.createElement("span");
    name.className = "result-name";
    name.textContent = item.name;
    const meta = document.createElement("span");
    meta.className = "result-meta";
    meta.textContent = `${item.source === "bazaar" ? "Bazaar" : "Auction"} · ${coins(item.price)}`;
    option.append(name, meta);
    option.addEventListener("mousedown", (event) => {
      event.preventDefault();
      choose(item);
    });
    list.append(option);
  });
  const open = state.results.length > 0;
  list.hidden = !open;
  input.setAttribute("aria-expanded", String(open));
  if (state.activeResult >= 0) {
    input.setAttribute("aria-activedescendant", `result-${state.activeResult}`);
    $(`result-${state.activeResult}`)?.scrollIntoView({ block: "nearest" });
  } else {
    input.removeAttribute("aria-activedescendant");
  }
}

function closeResults() {
  state.results = [];
  state.activeResult = -1;
  renderResults();
}

function choose(item) {
  closeResults();
  $("search-input").value = "";
  location.hash = `#${item.source}/${encodeURIComponent(item.key)}`;
}

function bindSearch() {
  const input = $("search-input");
  input.disabled = false;
  input.addEventListener("input", () => {
    state.results = search(input.value);
    state.activeResult = state.results.length ? 0 : -1;
    renderResults();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (!state.results.length) return;
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      state.activeResult = (state.activeResult + step + state.results.length) % state.results.length;
      renderResults();
    } else if (event.key === "Enter" && state.activeResult >= 0) {
      event.preventDefault();
      choose(state.results[state.activeResult]);
    } else if (event.key === "Escape") {
      closeResults();
    }
  });
  input.addEventListener("blur", closeResults);
}

function renderSuggestions() {
  const container = $("suggestions");
  container.replaceChildren();
  const picks = [
    ...state.items.filter((item) => item.source === "auctions").slice(0, 4),
    ...state.items.filter((item) => item.source === "bazaar").slice(0, 4),
  ];
  for (const item of picks) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "chip";
    chip.textContent = item.name;
    chip.addEventListener("click", () => choose(item));
    container.append(chip);
  }
}

/* ---------- item view ---------- */

function tile(label, value, note, title) {
  const element = document.createElement("div");
  element.className = "tile";
  const labelElement = document.createElement("p");
  labelElement.className = "tile-label";
  labelElement.textContent = label;
  const valueElement = document.createElement("p");
  valueElement.className = "tile-value";
  valueElement.textContent = value;
  if (title) valueElement.title = title;
  element.append(labelElement, valueElement);
  if (note) {
    const noteElement = document.createElement("p");
    noteElement.className = "tile-note";
    noteElement.textContent = note;
    element.append(noteElement);
  }
  return element;
}

function exact(value) {
  return value === null || value === undefined ? undefined : `${fullFormat.format(value)} coins`;
}

function bazaarTiles(product) {
  const trend = product.trend ?? {};
  const spread = product.buy !== null && product.sell !== null ? product.buy - product.sell : null;
  return [
    tile("Instant buy", coins(product.buy), trendNote(trend.buy_1d, trend.buy_7d), exact(product.buy)),
    tile("Instant sell", coins(product.sell), trendNote(trend.sell_1d, trend.sell_7d), exact(product.sell)),
    tile("Spread", coins(spread), spread !== null && product.buy ? `${percentFormat.format(spread / product.buy).replace("+", "")} of buy price` : null, exact(spread)),
    tile("Buy volume (7d)", count(product.buy_moving_week), `${count(product.buy_orders)} orders`),
    tile("Sell volume (7d)", count(product.sell_moving_week), `${count(product.sell_orders)} orders`),
  ];
}

function auctionTiles(item) {
  const trend = item.trend ?? {};
  const sales = item.sales;
  const lowest = item.lbin === null && item.last_seen
    ? tile("Last lowest BIN", coins(item.last_seen.lbin), `None listed now · seen ${ago(Date.now() / 1000 - item.last_seen.at)}`, exact(item.last_seen.lbin))
    : tile("Lowest BIN", coins(item.lbin), trendNote(trend.lbin_1d, trend.lbin_7d), exact(item.lbin));
  const tiles = [
    lowest,
    tile("Second lowest BIN", coins(item.lbin2), null, exact(item.lbin2)),
    tile("Active listings", count(item.listings)),
  ];
  if (sales) {
    const range = sales.p25_7d !== undefined ? `middle half ${coins(sales.p25_7d)}–${coins(sales.p75_7d)}` : null;
    tiles.push(
      tile("Median sale (24h)", coins(sales.median_1d), `${count(sales.count_1d)} sales`, exact(sales.median_1d)),
      tile("Median sale (7d)", coins(sales.median_7d), range ?? `${count(sales.count_7d)} sales`, exact(sales.median_7d)),
      tile("Est. sales per day", count(sales.est_volume_1d), sales.est_volume_1d === null ? "needs more coverage" : null),
    );
  } else {
    tiles.push(tile("Sales (7d)", "0", "no BIN sales recorded"));
  }
  return tiles;
}

function petLevels(item) {
  const container = $("item-levels");
  container.replaceChildren();
  const levels = new Set([...Object.keys(item.levels ?? {}), ...Object.keys(item.sales?.levels ?? {})]);
  if (!levels.size) return;
  const wrapper = document.createElement("div");
  wrapper.className = "levels table-scroll";
  const table = document.createElement("table");
  const caption = document.createElement("caption");
  caption.className = "visually-hidden";
  caption.textContent = "Prices by pet level";
  const head = table.createTHead().insertRow();
  for (const [text, numeric] of [["Level", false], ["Lowest BIN", true], ["Median sale (7d)", true], ["Sales (7d)", true]]) {
    const th = document.createElement("th");
    th.scope = "col";
    th.textContent = text;
    if (numeric) th.className = "num";
    head.append(th);
  }
  const body = table.createTBody();
  for (const level of [...levels].sort((a, b) => a - b)) {
    const sales = item.sales?.levels?.[level];
    const row = body.insertRow();
    const cells = [`Level ${level}`, coins(item.levels?.[level]), coins(sales?.median_7d), count(sales?.count_7d ?? 0)];
    cells.forEach((text, index) => {
      const cell = row.insertCell();
      cell.textContent = text;
      if (index) cell.className = "num";
    });
  }
  table.prepend(caption);
  wrapper.append(table);
  container.append(wrapper);
}

async function showItem(source, key) {
  const data = source === "bazaar" ? state.bazaar[key] : state.auctions[key];
  if (!data) {
    $("item").hidden = true;
    return;
  }
  state.current = { source, key, data };
  $("item").hidden = false;
  $("item-source").textContent = source === "bazaar" ? "Bazaar product" : "Auction house item";
  $("item-name").textContent = data.name ?? key;
  $("item-key").textContent = key;
  $("copy-key").textContent = "Copy key";
  $("item-tiles").replaceChildren(...(source === "bazaar" ? bazaarTiles(data) : auctionTiles(data)));
  if (source === "auctions") petLevels(data);
  else $("item-levels").replaceChildren();
  $("chart-title").textContent = source === "bazaar" ? "Instant buy and sell history" : "Lowest BIN history";
  document.title = `${data.name ?? key} · HSB Economy API`;
  await renderHistory();
}

async function loadHistory(source, key) {
  const cacheKey = `${source}/${key}`;
  if (!state.historyCache.has(cacheKey)) {
    // File names replace ':' (e.g. INK_SACK:3) so they stay portable.
    const path = `history/${source}/${encodeURIComponent(key.replaceAll(":", "-"))}.json`;
    state.historyCache.set(
      cacheKey,
      getJSON(path).catch(() => ({})),
    );
  }
  return state.historyCache.get(cacheKey);
}

async function renderHistory() {
  const current = state.current;
  if (!current) return;
  const history = await loadHistory(current.source, current.key);
  if (state.current !== current) return;
  const series = SERIES[current.source].map((config) => {
    const points = history[config.metric]?.[state.range] ?? { t: [], v: [] };
    return { ...config, points: points.t.map((t, index) => [t, points.v[index]]) };
  });
  chart.render(series, RESOLUTION[state.range], $("chart-title").textContent);
}

function bindItemControls() {
  for (const button of document.querySelectorAll(".segmented button")) {
    button.addEventListener("click", () => {
      state.range = button.dataset.range;
      for (const other of document.querySelectorAll(".segmented button")) {
        other.setAttribute("aria-pressed", String(other === button));
      }
      renderHistory();
    });
  }
  $("copy-key").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText($("item-key").textContent);
      $("copy-key").textContent = "Copied";
    } catch {
      $("copy-key").textContent = "Copy failed";
    }
  });
}

function route() {
  const match = /^#(bazaar|auctions)\/(.+)$/.exec(location.hash);
  if (!match) {
    $("item").hidden = true;
    document.title = "HSB Economy API";
    return;
  }
  showItem(match[1], decodeURIComponent(match[2]));
}

/* ---------- chart ---------- */

function svg(tag, attributes = {}, parent) {
  const element = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attributes)) element.setAttribute(name, value);
  parent?.append(element);
  return element;
}

function niceStep(span, targetTicks) {
  const raw = span / targetTicks;
  const magnitude = 10 ** Math.floor(Math.log10(raw));
  const normalized = raw / magnitude;
  return (normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 2.5 ? 2.5 : normalized <= 5 ? 5 : 10) * magnitude;
}

function valueTicks(min, max) {
  if (min === max) {
    const pad = Math.abs(min) * 0.05 || 1;
    min -= pad;
    max += pad;
  }
  const step = niceStep(max - min, 4);
  const start = Math.floor(min / step) * step;
  const end = Math.ceil(max / step) * step;
  const ticks = [];
  for (let value = start; value <= end + step / 2; value += step) ticks.push(value);
  return ticks;
}

function timeTicks(min, max) {
  const span = max - min;
  const offset = new Date().getTimezoneOffset() * 60;
  if (span > 120 * DAY) {
    const ticks = [];
    const date = new Date(min * 1000);
    date.setDate(1);
    date.setHours(0, 0, 0, 0);
    const monthStep = span > 300 * DAY ? 2 : 1;
    while (date.getTime() / 1000 <= max) {
      if (date.getTime() / 1000 >= min) ticks.push(date.getTime() / 1000);
      date.setMonth(date.getMonth() + monthStep);
    }
    return { ticks, format: new Intl.DateTimeFormat(undefined, { month: "short" }) };
  }
  const steps = [6 * HOUR, 12 * HOUR, DAY, 2 * DAY, 7 * DAY, 14 * DAY];
  const step = steps.find((candidate) => span / candidate <= 6) ?? 30 * DAY;
  const ticks = [];
  // Align to local midnight so day ticks land on day boundaries.
  for (let t = Math.ceil((min - offset) / step) * step + offset; t <= max; t += step) ticks.push(t);
  const format = step < DAY
    ? new Intl.DateTimeFormat(undefined, { hour: "numeric" })
    : new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" });
  return { ticks, format };
}

const chart = {
  container: null,
  last: null,
  tooltip: null,

  init() {
    this.container = $("chart");
    new ResizeObserver(() => {
      if (this.last) requestAnimationFrame(() => this.draw(...this.last));
    }).observe(this.container);
  },

  render(series, resolution, title) {
    this.last = [series, resolution, title];
    this.draw(series, resolution, title);
    this.legend(series);
    this.table(series, resolution);
  },

  color(series) {
    return getComputedStyle(document.documentElement).getPropertyValue(series.color).trim();
  },

  legend(series) {
    const legend = $("chart-legend");
    legend.replaceChildren();
    // A single series is named by the chart title; a legend box would only repeat it.
    if (series.length < 2) return;
    for (const entry of series) {
      const key = document.createElement("span");
      key.className = "legend-key";
      const line = document.createElement("span");
      line.className = "line-key";
      line.style.background = this.color(entry);
      const label = document.createElement("span");
      label.textContent = entry.label;
      key.append(line, label);
      legend.append(key);
    }
  },

  table(series, resolution) {
    const container = $("chart-table");
    container.replaceChildren();
    const times = [...new Set(series.flatMap((entry) => entry.points.map(([t]) => t)))].sort((a, b) => b - a);
    if (!times.length) {
      container.textContent = "No history recorded yet.";
      return;
    }
    const lookups = series.map((entry) => new Map(entry.points));
    const wrapper = document.createElement("div");
    wrapper.className = "table-scroll";
    const table = document.createElement("table");
    const head = table.createTHead().insertRow();
    for (const text of ["Time", ...series.map((entry) => entry.label)]) {
      const th = document.createElement("th");
      th.scope = "col";
      th.textContent = text;
      if (text !== "Time") th.className = "num";
      head.append(th);
    }
    const body = table.createTBody();
    for (const t of times) {
      const row = body.insertRow();
      row.insertCell().textContent = formatTime(t, resolution);
      for (const lookup of lookups) {
        const cell = row.insertCell();
        cell.className = "num";
        cell.textContent = lookup.has(t) ? fullFormat.format(lookup.get(t)) : "—";
      }
    }
    wrapper.append(table);
    container.append(wrapper);
  },

  draw(series, resolution, title) {
    const container = this.container;
    container.replaceChildren();
    const width = Math.max(container.clientWidth, 280);
    const height = 260;
    const margin = { top: 12, right: series.length > 1 ? 16 : 64, bottom: 28, left: 56 };
    const root = svg("svg", { viewBox: `0 0 ${width} ${height}`, width, height, role: "img", tabindex: "0" }, container);

    const all = series.flatMap((entry) => entry.points);
    if (all.length < 2) {
      root.setAttribute("aria-label", `${title}: not enough history yet`);
      const message = svg("text", { x: width / 2, y: height / 2, "text-anchor": "middle", class: "empty" }, root);
      message.textContent = "Not enough history yet. Points are added every hour.";
      return;
    }

    const times = all.map(([t]) => t);
    const values = all.map(([, v]) => v);
    let tMin = Math.min(...times);
    let tMax = Math.max(...times);
    if (tMin === tMax) {
      tMin -= resolution;
      tMax += resolution;
    }
    const yTicks = valueTicks(Math.min(...values), Math.max(...values));
    const yMin = yTicks[0];
    const yMax = yTicks[yTicks.length - 1];
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;
    const x = (t) => margin.left + ((t - tMin) / (tMax - tMin)) * plotWidth;
    const y = (v) => margin.top + (1 - (v - yMin) / (yMax - yMin)) * plotHeight;

    const grid = svg("g", { class: "grid" }, root);
    for (const tick of yTicks) {
      svg("line", { x1: margin.left, x2: width - margin.right, y1: y(tick), y2: y(tick) }, grid);
      const label = svg("text", { x: margin.left - 8, y: y(tick), "text-anchor": "end", "dominant-baseline": "middle", class: "tick" }, root);
      label.textContent = coins(tick);
    }
    svg("line", { x1: margin.left, x2: width - margin.right, y1: margin.top + plotHeight, y2: margin.top + plotHeight, class: "baseline" }, root);
    const { ticks: xTicks, format: xFormat } = timeTicks(tMin, tMax);
    for (const tick of xTicks) {
      const label = svg("text", { x: x(tick), y: height - 8, "text-anchor": "middle", class: "tick" }, root);
      label.textContent = xFormat.format(new Date(tick * 1000));
    }

    const surface = getComputedStyle(document.documentElement).getPropertyValue("--surface").trim();
    const endLabels = [];
    for (const entry of series) {
      if (!entry.points.length) continue;
      const color = this.color(entry);
      // Break the line across gaps (missed runs) instead of interpolating through them.
      const segments = [];
      let segment = [];
      entry.points.forEach(([t, v], index) => {
        if (index && t - entry.points[index - 1][0] > resolution * 1.5) {
          segments.push(segment);
          segment = [];
        }
        segment.push([t, v]);
      });
      segments.push(segment);
      for (const points of segments) {
        if (points.length === 1) {
          svg("circle", { cx: x(points[0][0]), cy: y(points[0][1]), r: 4, fill: color, stroke: surface, "stroke-width": 2 }, root);
          continue;
        }
        const d = points.map(([t, v], index) => `${index ? "L" : "M"}${x(t).toFixed(1)},${y(v).toFixed(1)}`).join("");
        if (series.length === 1) {
          const base = (margin.top + plotHeight).toFixed(1);
          const area = `${d}L${x(points.at(-1)[0]).toFixed(1)},${base}L${x(points[0][0]).toFixed(1)},${base}Z`;
          svg("path", { d: area, fill: color, "fill-opacity": 0.1, stroke: "none" }, root);
        }
        svg("path", { d, fill: "none", stroke: color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round" }, root);
      }
      const [lastT, lastV] = entry.points.at(-1);
      svg("circle", { cx: x(lastT), cy: y(lastV), r: 4, fill: color, stroke: surface, "stroke-width": 2 }, root);
      endLabels.push({ x: x(lastT), y: y(lastV), value: lastV });
    }
    // Direct-label the latest value only when one series is plotted; two converging labels would collide.
    if (endLabels.length === 1) {
      const [label] = endLabels;
      const text = svg("text", { x: label.x + 8, y: label.y, "dominant-baseline": "middle", class: "end-label" }, root);
      text.textContent = coins(label.value);
    }

    const latest = series.filter((entry) => entry.points.length).map((entry) => `${entry.label} ${coins(entry.points.at(-1)[1])}`);
    root.setAttribute(
      "aria-label",
      `${title}, ${formatTime(tMin, resolution)} to ${formatTime(tMax, resolution)}. Latest: ${latest.join(", ")}. ` +
        "Use the arrow keys to read values, or open the data table below.",
    );
    this.hover(root, series, resolution, { x, y, margin, plotWidth, plotHeight, surface });
  },

  hover(root, series, resolution, frame) {
    const times = [...new Set(series.flatMap((entry) => entry.points.map(([t]) => t)))].sort((a, b) => a - b);
    const lookups = series.map((entry) => new Map(entry.points));
    const layer = svg("g", { "pointer-events": "none" }, root);
    const tooltip = document.createElement("div");
    tooltip.className = "tooltip";
    tooltip.hidden = true;
    this.container.append(tooltip);
    let index = -1;

    const show = (nextIndex) => {
      index = Math.max(0, Math.min(times.length - 1, nextIndex));
      const t = times[index];
      layer.replaceChildren();
      const cx = frame.x(t);
      svg("line", { x1: cx, x2: cx, y1: frame.margin.top, y2: frame.margin.top + frame.plotHeight, class: "crosshair" }, layer);
      const time = document.createElement("div");
      time.className = "tooltip-time";
      time.textContent = formatTime(t, resolution);
      const rows = [time];
      series.forEach((entry, seriesIndex) => {
        const value = lookups[seriesIndex].get(t);
        if (value === undefined) return;
        const color = this.color(entry);
        svg("circle", { cx, cy: frame.y(value), r: 4, fill: color, stroke: frame.surface, "stroke-width": 2 }, layer);
        const row = document.createElement("div");
        row.className = "tooltip-row";
        const key = document.createElement("span");
        key.className = "line-key";
        key.style.background = color;
        const strong = document.createElement("strong");
        strong.textContent = coins(value);
        strong.title = `${fullFormat.format(value)} coins`;
        const label = document.createElement("span");
        label.textContent = entry.label;
        row.append(key, strong, label);
        rows.push(row);
      });
      tooltip.replaceChildren(...rows);
      tooltip.hidden = false;
      const box = this.container.getBoundingClientRect();
      const scale = box.width / Number(root.getAttribute("width"));
      const left = cx * scale;
      const flip = left + tooltip.offsetWidth + 16 > box.width;
      tooltip.style.left = `${flip ? left - tooltip.offsetWidth - 12 : left + 12}px`;
      tooltip.style.top = `${frame.margin.top * scale}px`;
    };
    const hide = () => {
      layer.replaceChildren();
      tooltip.hidden = true;
      index = -1;
    };
    const nearest = (clientX) => {
      const box = root.getBoundingClientRect();
      const svgX = ((clientX - box.left) / box.width) * Number(root.getAttribute("width"));
      let best = 0;
      for (let candidate = 1; candidate < times.length; candidate++) {
        if (Math.abs(frame.x(times[candidate]) - svgX) < Math.abs(frame.x(times[best]) - svgX)) best = candidate;
      }
      return best;
    };

    root.addEventListener("pointermove", (event) => show(nearest(event.clientX)));
    root.addEventListener("pointerleave", hide);
    root.addEventListener("blur", hide);
    root.addEventListener("keydown", (event) => {
      const moves = { ArrowLeft: -1, ArrowRight: 1 };
      if (event.key in moves) {
        event.preventDefault();
        show(index < 0 ? times.length - 1 : index + moves[event.key]);
      } else if (event.key === "Home" || event.key === "End") {
        event.preventDefault();
        show(event.key === "Home" ? 0 : times.length - 1);
      } else if (event.key === "Escape") {
        hide();
      }
    });
  },
};

/* ---------- start ---------- */

function renderExample() {
  $("base-url").textContent = API.href;
  $("example").textContent =
    `const { prices } = await (await fetch("${new URL("prices.json", API).href}")).json();\n` +
    `console.log(prices["HYPERION"]);`;
}

async function init() {
  renderExample();
  chart.init();
  bindItemControls();
  try {
    const [meta, bazaar, auctions] = await Promise.all([getJSON("meta.json"), getJSON("bazaar.json"), getJSON("auctions.json")]);
    state.bazaar = bazaar.products;
    state.auctions = auctions.items;
    buildIndex();
    renderStatus(meta);
  } catch (error) {
    renderError(error);
    return;
  }
  bindSearch();
  renderSuggestions();
  window.addEventListener("hashchange", route);
  route();
}

init();
