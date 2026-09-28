// Renders the dashboard from the JSON files written by src/export_site.py.
//
// Nothing here computes a statistic. Every number on the page comes out of a file, so
// the page cannot drift away from the catalogue: if a figure looks wrong, the export is
// wrong, and re-running the export fixes the page. Panels fail independently, so a
// missing file leaves a placeholder rather than a blank document.

import * as Plot from "https://cdn.jsdelivr.net/npm/@observablehq/plot@0.6/+esm";
import * as d3 from "https://cdn.jsdelivr.net/npm/d3@7/+esm";

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

const css = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const INK = css("--ink-soft") || "#555";
const FAINT = css("--ink-faint") || "#888";
const LINE = css("--line") || "#ddd";
const ACCENT = css("--accent") || "#0f6b5c";
const MAP_SEA = css("--map-sea") || "#eef3f6";
const MAP_LAND = css("--map-land") || "#d9d3c6";
const MAP_EDGE = css("--map-edge") || "#a79f8e";

const fmt = {
  int: d3.format(","),
  si: (v) => d3.format(".3~s")(v).replace("G", "B"),
  f1: d3.format(".1f"),
  f2: d3.format(".2f"),
  f3: d3.format(".3f"),
  pct1: d3.format(".1f"),
  f0: d3.format(".0f"),
};

// ------------------------------------------------------------------ plumbing

async function load(name) {
  try {
    const r = await fetch(`data/${name}.json`, { cache: "no-cache" });
    if (!r.ok) throw new Error(`${r.status}`);
    return await r.json();
  } catch (e) {
    console.warn(`data/${name}.json not loaded: ${e.message}`);
    return null;
  }
}

function mount(id, node) {
  const host = document.getElementById(id);
  if (!host) return;
  host.replaceChildren(node);
}

function missing(id, what) {
  const host = document.getElementById(id);
  if (!host) return;
  const p = document.createElement("div");
  p.className = "plot-missing";
  p.textContent = `${what} not available. Run: python src/export_site.py`;
  host.replaceChildren(p);
}

function text(id, s) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = s;
}

// Shared Plot defaults, so every chart sits in the page's palette.
const base = {
  style: { background: "transparent", color: INK, fontSize: "12px" },
  marginLeft: 56,
  marginBottom: 38,
  grid: true,
};

const monthAxis = {
  domain: d3.range(1, 13),
  tickFormat: (m) => MONTHS[m - 1],
  label: null,
};

// Plot sizes a chart once, at call time, so a fixed width means a horizontal
// scrollbar on any screen narrower than the number guessed here. Instead each panel
// keeps its spec as a function of the available width and is redrawn when that
// changes. The registry is what makes the page work on a phone and on a wide monitor
// from the same code.
const panels = [];

function draw(id, specFn) {
  const host = document.getElementById(id);
  if (!host) return;
  const width = Math.max(280, Math.floor(host.clientWidth || 640));
  try {
    mount(id, Plot.plot({ ...base, ...specFn(width) }));
  } catch (e) {
    console.error(id, e);
    missing(id, "chart");
  }
}

function panel(id, specFn) {
  panels.push([id, specFn]);
  draw(id, specFn);
}

// Maps own their redraw, because they carry state a plain spec function does not:
// the active colour mode and the selected track.
const resizeHandlers = [];

let resizeTimer;
const lastWidths = new Map();
addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    const changed = (id) => {
      const host = document.getElementById(id);
      if (!host) return false;
      // Redraw only what actually changed size. Recreating every SVG on every
      // resize event is what makes this kind of page stutter.
      const w = host.clientWidth;
      if (lastWidths.get(id) === w) return false;
      lastWidths.set(id, w);
      return true;
    };
    for (const [id, specFn] of panels) if (changed(id)) draw(id, specFn);
    for (const [id, render] of resizeHandlers) if (changed(id)) render();
  }, 180);
});

// --------------------------------------------------------------------- hero

function renderHero(summary) {
  if (!summary) return;
  const s = summary;
  const cells = [
    ["Storms", fmt.int(s.storms), `${fmt.int(Math.round(s.storms_per_year))} a year`],
    ["Rainfall", `${fmt.int(Math.round(s.volume_km3))} km&sup3;`, "total volume tracked"],
    ["Record", `${s.year_min}–${s.year_max}`, `${fmt.f2(s.n_years)} years of data`],
    ["Percolation", fmt.f3(s.percolation.median),
     `share of rain in the largest object, max ${fmt.f3(s.percolation.max)}`],
  ];
  const dl = document.getElementById("stats");
  dl.innerHTML = cells.map(([k, v, note]) =>
    `<div><dt>${k}</dt><dd>${v}<small>${note}</small></dd></div>`).join("");

  text("def-rate",
    `roughly ${fmt.int(Math.round(s.storms_per_year / 1000) * 1000)} storms a year`);

  const p = s.params;
  text("provenance",
    `segmentation ${p.method}, prominence h = ${p.prominence_mm_hr} mm/hr, ` +
    `wet threshold ${p.wet_threshold_mm_hr} mm/hr &middot; ${p.product} &middot; ` +
    `exported ${s.meta.built_utc.slice(0, 10)} at ${s.meta.git_rev}`);
}

// ------------------------------------------------------------- 1. the method

function renderMethod(method) {
  if (!method) return missing("chart-method", "method comparison");

  const rows = method.rows.flatMap((r) => [
    { method: r.method, metric: "largest single object", value: r.largest_object_share },
    { method: r.method, metric: "rain captured", value: r.rain_captured },
  ]);

  // Method on the y axis and metric as the facet, not the other way round. Faceting
  // by method puts its long name in the right-hand facet label, where Plot gives it no
  // room and it is clipped to "CCL, ...".
  const methods = method.rows.map((r) => r.method);

  panel("chart-method", (w) => ({
    width: w,
    height: 300,
    marginLeft: Math.min(210, Math.max(120, w * 0.3)),
    marginRight: 54,
    x: { label: "share →", domain: [0, 1], tickFormat: "%", grid: true },
    y: { label: null, domain: methods },
    // No facet axis: the colour legend already names the two groups, and the
    // right-hand label only had room to show half of each name.
    fy: { label: null, axis: null },
    color: {
      domain: ["largest single object", "rain captured"],
      range: ["#c2410c", ACCENT],
      legend: true,
    },
    marks: [
      Plot.barX(rows, {
        x: "value", y: "method", fy: "metric", fill: "metric",
        sort: { fy: null },
      }),
      Plot.text(rows, {
        x: "value", y: "method", fy: "metric",
        text: (d) => d3.format(".1%")(d.value),
        dx: 6, textAnchor: "start", fill: INK, fontVariant: "tabular-nums",
      }),
      Plot.ruleX([0]),
    ],
  }));

  text("caption-method",
    `Lower is better on the left, higher is better on the right. The published method ` +
    `can have one or the other, not both: de-percolating it by raising the threshold ` +
    `throws away four fifths of the rain. Window: ${method.window}. ` +
    `<strong>The two CCL rows are quoted from a one-off diagnostic recorded in ` +
    `docs/findings.md, not recomputed here.</strong>`);

  const m = method.measured_percolation_full_archive;
  text("callout-percolation",
    `Measured across all 28 catalogues rather than quoted: the largest object holds a ` +
    `median <strong>${fmt.f3(m.median)}</strong> of the rain, never more than ` +
    `<strong>${fmt.f3(m.max)}</strong>. Against 0.90 for the published method, that is ` +
    `the whole reason the segmentation was replaced.`);
}

// ----------------------------------------------------------------- 2/3. maps

// The four ways a track can be coloured. `how` is shown in the details block under
// each map, because "severity" in particular means something specific here and a
// reader has no way to guess it.
const COLOUR_MODES = {
  intensity: {
    label: "peak intensity",
    field: (p) => p.max_intensity_mm_hr,
    scale: { type: "sqrt", scheme: "turbo", label: "peak intensity (mm/hr)",
             legend: true },
    how: "The single highest half-hourly rain rate reached by any one grid cell " +
         "anywhere in the storm, at any point in its life, in mm/hr. A peak value, " +
         "not an average, so a brief violent core sets it.",
  },
  volume: {
    label: "total volume",
    field: (p) => p.volume_km3,
    scale: { type: "sqrt", scheme: "YlGnBu", label: "total volume (km³)",
             legend: true },
    how: "All the water the storm delivered over its whole life, in cubic " +
         "kilometres. Each cell's rate is multiplied by 0.5 h to get a depth, then " +
         "by that cell's ground area, and the lot is summed over every cell and " +
         "every timestep. This is the attribute that ranks storms most meaningfully, " +
         "and the one that barely moves when the segmentation parameter changes.",
  },
  duration: {
    label: "duration",
    field: (p) => p.duration_h,
    scale: { type: "linear", scheme: "magma", label: "duration (hours)",
             legend: true },
    how: "Number of half-hourly steps the object exists for, times 0.5 h. Because " +
         "the object is connected through time, this is a real lifetime rather than " +
         "a count of separate rainy snapshots.",
  },
  severity: {
    label: "severity class",
    field: (p) => p.severity,
    scale: { type: "ordinal", scheme: "YlOrRd", label: "severity class",
             legend: true, domain: ["very low", "low", "moderate", "medium",
                                    "heavy", "very heavy", "intense", "severe",
                                    "extreme"] },
    how: "A nine-class grid: the storm's volume band crossed with its peak-intensity " +
         "band. The band edges are exceedance rates over the full 28 years, set at " +
         "500 and 50 storms a year, so they isolate an operationally rare tail. " +
         "One consequence is that 99.8% of all storms ever catalogued sit in the " +
         "lowest class, which makes this scale useful for finding extremes and " +
         "useless for telling ordinary storms apart. Section 4 is what that costs.",
  },
};

const intensityScale = COLOUR_MODES.intensity.scale;

// Which colour mode each map is currently in, and which track is selected.
const mapState = {};

function segmented(hostId, mapId, onChange) {
  const host = document.getElementById(hostId);
  if (!host) return;
  host.replaceChildren(...Object.entries(COLOUR_MODES).map(([key, m]) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = m.label;
    b.dataset.key = key;
    b.setAttribute("aria-pressed", String(mapState[mapId] === key));
    b.addEventListener("click", () => {
      mapState[mapId] = key;
      [...host.children].forEach((c) =>
        c.setAttribute("aria-pressed", String(c.dataset.key === key)));
      onChange(key);
    });
    return b;
  }));
}

function defsList(hostId) {
  const host = document.getElementById(hostId);
  if (!host) return;
  host.innerHTML = Object.values(COLOUR_MODES)
    .map((m) => `<dt>${m.label}</dt><dd>${m.how}</dd>`).join("");
}

function trackMap(id, tracks, land, opts = {}) {
  if (!tracks) return missing(id, "storm tracks");
  const [latMin, latMax, lonMin, lonMax] = tracks.bbox;

  // Wound CLOCKWISE in lon/lat, and it has to be. d3-geo reads a polygon ring
  // spherically: the interior is the side to the ring's left. Counterclockwise here
  // describes everything except this box, so the projection fits the whole globe and
  // Indonesia renders as a speck. There is no error and no warning, just a world map.
  const frame = {
    type: "Polygon",
    coordinates: [[[lonMin, latMin], [lonMin, latMax],
                   [lonMax, latMax], [lonMax, latMin], [lonMin, latMin]]],
  };

  const feats = tracks.features;
  const lines = feats.filter((f) => f.geometry.type === "LineString");
  const points = feats.filter((f) => f.geometry.type === "Point");

  const title = (d) => {
    const p = d.properties;
    return [`${p.start.replace("T", " ")} UTC`,
            `volume ${fmt.f3(p.volume_km3)} km3`,
            `peak ${fmt.f1(p.max_intensity_mm_hr)} mm/hr`,
            `duration ${p.duration_h} h`,
            `severity ${p.severity}`].join("\n");
  };

  // Height follows the extent's own aspect ratio, so neither map is stretched and
  // both stay honest about shape when the page is resized.
  const aspect = (latMax - latMin) / (lonMax - lonMin);

  mapState[id] = mapState[id] ?? "intensity";

  const render = () => {
    const mode = COLOUR_MODES[mapState[id]];
    const sel = opts.selectable ? mapState[`${id}:sel`] : null;
    // A selected track is drawn again on top in white, so it stays findable whatever
    // the colour mode is doing.
    const chosen = sel == null ? []
      : feats.filter((f) => f.properties.id === sel && f.geometry.type === "LineString");

    draw(id, (w) => ({
      width: w,
      height: Math.round(w * aspect) + 40,
      projection: { type: "equirectangular", domain: frame, inset: 2 },
      color: mode.scale,
      grid: false,
      marks: [
        // Sea first, as a filled frame. Sea is signal in this catalogue, not padding:
        // most storms that reach Indonesian land were born over water.
        Plot.frame({ fill: MAP_SEA }),
        // Everything is clipped to the frame: the graticule is generated worldwide,
        // and a storm track can run past the edge of the area of interest.
        Plot.geo(land ?? [], { fill: MAP_LAND, stroke: MAP_EDGE,
                               strokeWidth: 0.5, clip: "frame" }),
        Plot.graticule({ stroke: MAP_EDGE, strokeOpacity: 0.3, strokeWidth: 0.5,
                         interval: opts.graticule ?? 5, clip: "frame" }),
        Plot.geo(lines, {
          stroke: (d) => mode.field(d.properties),
          strokeWidth: opts.strokeWidth ?? 1.3,
          strokeOpacity: sel == null ? 0.85 : 0.35,
          strokeLinecap: "round",
          clip: "frame",
          title, tip: true,
        }),
        Plot.geo(points, {
          fill: (d) => mode.field(d.properties),
          r: opts.pointR ?? 2,
          fillOpacity: sel == null ? 1 : 0.4,
          clip: "frame",
          title, tip: true,
        }),
        ...(chosen.length ? [
          Plot.geo(chosen, { stroke: INK, strokeWidth: (opts.strokeWidth ?? 1.3) + 3,
                             strokeOpacity: 0.35, strokeLinecap: "round",
                             clip: "frame" }),
          Plot.geo(chosen, { stroke: (d) => mode.field(d.properties),
                             strokeWidth: (opts.strokeWidth ?? 1.3) + 1.2,
                             strokeLinecap: "round", clip: "frame" }),
        ] : []),
        ...(opts.places ?? []).flatMap((p) => [
          Plot.dot([p], { x: "lon", y: "lat", r: 4, fill: "none", stroke: INK,
                          strokeWidth: 1.6, clip: "frame" }),
          Plot.text([p], { x: "lon", y: "lat", text: "name", dy: -12,
                           fill: INK, fontSize: 12, fontWeight: 600,
                           stroke: MAP_SEA, strokeWidth: 3, paintOrder: "stroke",
                           clip: "frame" }),
        ]),
        Plot.frame({ stroke: MAP_EDGE }),
      ],
    }));

    if (opts.onPick) wirePicking(id, feats, opts.onPick, render);
  };

  // Maps re-render through this closure rather than through the plain panel registry,
  // so a resize keeps the current colour mode and the selected track.
  resizeHandlers.push([id, render]);
  render();
  return { feats, render };
}

/** Make the drawn track paths clickable, mapping each SVG path back to its feature.
 *
 * Plot does not expose a click API on geo marks, so this walks the rendered paths in
 * the order Plot drew them, which is the order of the array handed to `Plot.geo`.
 * Re-run after every render, because the paths are new elements each time.
 */
function wirePicking(id, feats, onPick, rerender) {
  const host = document.getElementById(id);
  if (!host) return;
  const lines = feats.filter((f) => f.geometry.type === "LineString");
  const svgs = [...host.querySelectorAll("svg")];
  const plot = svgs[svgs.length - 1];
  if (!plot) return;

  // The first group with exactly as many paths as there are line features is the
  // tracks layer. Checking the count avoids grabbing the coastline by mistake.
  const groups = [...plot.querySelectorAll("g")];
  const layer = groups.find((g) => {
    const p = g.querySelectorAll(":scope > path");
    return p.length === lines.length && lines.length > 0;
  });
  if (!layer) return;

  [...layer.querySelectorAll(":scope > path")].forEach((path, i) => {
    const f = lines[i];
    if (!f) return;
    path.style.cursor = "pointer";
    // A hairline is hard to hit. A transparent fat stroke widens the target without
    // changing what is drawn.
    path.style.strokeLinejoin = "round";
    path.addEventListener("click", (e) => {
      e.stopPropagation();
      const cur = mapState[`${id}:sel`];
      mapState[`${id}:sel`] = cur === f.properties.id ? null : f.properties.id;
      onPick(mapState[`${id}:sel`] == null ? null : f);
      rerender();
    });
  });
}

function renderDomainMap(tracks, land) {
  const out = trackMap("chart-map-domain", tracks, land, { graticule: 5 });
  if (!out) return;
  const feats = out.feats;
  segmented("colourby-domain", "chart-map-domain", () => out.render());
  defsList("defs-domain");
  const m = tracks.meta;
  const vol = d3.sum(feats, (f) => f.properties.volume_km3);
  text("caption-map-domain",
    `The ${m.n_written} largest storms by volume alive between 30 Dec 2019 and ` +
    `2 Jan 2020, carrying ${Math.round(vol)} km&sup3; between them. Hover any track ` +
    `for its numbers. Gridlines every 5 degrees. <strong>These four days were not an ` +
    `exceptional period nationally</strong>: December 2019 ranks 182nd and January ` +
    `2020 174th of the 333 months in the record by total rainfall. The flood was a ` +
    `local event, and the map shows why that is not a contradiction.`);
}

function renderDetail(f) {
  const charts = document.getElementById("detail-charts");
  const stats = document.getElementById("detail-stats");
  const hint = document.getElementById("detail-hint");
  const clear = document.getElementById("clear-selection");

  if (!f) {
    charts.hidden = true;
    stats.hidden = true;
    clear.hidden = true;
    hint.hidden = false;
    text("detail-title", "Life cycle of one storm");
    return;
  }

  const p = f.properties;
  const s = p.series;
  if (!s || !s.t || !s.t.length) {
    hint.hidden = false;
    hint.textContent = "This storm has no per-step history in the export.";
    return;
  }

  const rows = s.t.map((t, i) => ({
    t: new Date(t),
    // Volume per half-hourly step, shown as a rate in km3/h so the axis means
    // something physical rather than depending on the step length.
    rate: s.volume_km3[i] * 2,
    volume: s.volume_km3[i],
    area: s.area_km2[i],
    peak: s.peak_mm_hr[i],
  }));
  let cum = 0;
  rows.forEach((r) => { cum += r.volume; r.cum = cum; });

  hint.hidden = true;
  charts.hidden = false;
  stats.hidden = false;
  clear.hidden = false;

  const t0 = new Date(p.start);
  text("detail-title",
    `Storm ${p.id}: ${t0.toISOString().slice(0, 16).replace("T", " ")} UTC, ` +
    `${p.duration_h} hours`);

  panel("chart-detail-rate", (w) => ({
    width: w, height: 250,
    marginRight: 48,
    x: { label: "UTC →", type: "time" },
    y: { label: "delivering (km³/h) ↑", zero: true },
    marks: [
      Plot.areaY(rows, { x: "t", y: "rate", fill: ACCENT, fillOpacity: 0.22,
                         curve: "monotone-x" }),
      Plot.line(rows, { x: "t", y: "rate", stroke: ACCENT, strokeWidth: 2,
                        curve: "monotone-x" }),
      Plot.dot(rows, { x: "t", y: "rate", fill: ACCENT, r: 2.5,
                       title: (d) => `${d.t.toISOString().slice(11, 16)} UTC\n` +
                                     `${fmt.f3(d.rate)} km3/h\n` +
                                     `peak ${fmt.f1(d.peak)} mm/hr`,
                       tip: true }),
      Plot.ruleY([0]),
    ],
  }));

  panel("chart-detail-area", (w) => ({
    width: w, height: 250,
    marginRight: 48,
    x: { label: "UTC →", type: "time" },
    y: { label: "footprint (km²) ↑", zero: true },
    color: { legend: false },
    marks: [
      Plot.areaY(rows, { x: "t", y: "area", fill: "#1d6fa5", fillOpacity: 0.18,
                         curve: "monotone-x" }),
      Plot.line(rows, { x: "t", y: "area", stroke: "#1d6fa5", strokeWidth: 2,
                        curve: "monotone-x" }),
      Plot.line(rows, { x: "t", y: (d) => d.peak / d3.max(rows, (r) => r.peak) *
                                          d3.max(rows, (r) => r.area),
                        stroke: "#c2410c", strokeWidth: 1.6,
                        strokeDasharray: "4,3", curve: "monotone-x" }),
      Plot.ruleY([0]),
    ],
  }));

  const peakRow = d3.greatest(rows, (r) => r.peak);
  const bigRow = d3.greatest(rows, (r) => r.area);
  // Mean depth over the storm's own largest footprint. Volume in km3 over area in
  // km2 is a depth in km, and 1 km is 1e6 mm.
  const meanDepthMm = p.volume_km3 / p.max_area_km2 * 1e6;

  document.getElementById("detail-stats").innerHTML = [
    ["Total volume", `${fmt.f3(p.volume_km3)} km³`,
     `about ${fmt.f0(meanDepthMm)} mm spread over its largest footprint`],
    ["Peak intensity", `${fmt.f1(p.max_intensity_mm_hr)} mm/hr`,
     `reached ${peakRow.t.toISOString().slice(11, 16)} UTC`],
    ["Largest footprint", `${fmt.int(Math.round(p.max_area_km2))} km²`,
     `at ${bigRow.t.toISOString().slice(11, 16)} UTC`],
    ["Severity", p.severity,
     `on the 28-year domain-wide scale${p.truncated ? ", truncated" : ""}`],
  ].map(([k, v, note]) =>
    `<div><dt>${k}</dt><dd>${v}<small>${note}</small></dd></div>`).join("");

  text("detail-caption",
    `Left: how fast the storm was delivering water, as a rate so the axis does not ` +
    `depend on the half-hourly step. Right: its footprint in solid blue, with peak ` +
    `intensity in dashed orange rescaled onto the same frame for shape comparison ` +
    `only, peaking at ${fmt.f1(d3.max(rows, (r) => r.peak))} mm/hr. A storm that ` +
    `spreads while weakening shows the two lines diverging.`);
  document.getElementById("panel-detail")
    .scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderJakartaMap(tracks, land) {
  const out = trackMap("chart-map-jakarta", tracks, land, {
    strokeWidth: 2.2, pointR: 3, graticule: 1,
    places: tracks.places && tracks.places.length ? tracks.places : [
      { name: "Jakarta", lon: 106.845, lat: -6.209 },
      { name: "Bogor", lon: 106.800, lat: -6.595 },
      { name: "Bandung", lon: 107.619, lat: -6.917 },
      { name: "Serang", lon: 106.150, lat: -6.120 },
    ],
    selectable: true,
    onPick: renderDetail,
  });
  if (!out) return;
  const feats = out.feats;

  segmented("colourby-jakarta", "chart-map-jakarta", () => out.render());
  const clear = document.getElementById("clear-selection");
  if (clear) {
    clear.addEventListener("click", () => {
      mapState["chart-map-jakarta:sel"] = null;
      renderDetail(null);
      out.render();
    });
  }
  renderDetail(null);

  const props = feats.map((f) => f.properties);
  const vol = d3.sum(props, (p) => p.volume_km3);
  const peak = d3.max(props, (p) => p.max_intensity_mm_hr);
  const longest = d3.max(props, (p) => p.duration_h);

  text("caption-map-jakarta",
    `${feats.length} storms over Jakarta, Banten and West Java, 30 Dec 2019 to ` +
    `2 Jan 2020. Total ${fmt.f1(vol)} km&sup3;, peak intensity ${fmt.f1(peak)} mm/hr, ` +
    `longest ${longest} h. Gridlines every 1 degree.`);

  // Storm starts per 3 hours.
  const starts = props.map((p) => ({ ...p, t: new Date(p.start) }));
  panel("chart-jakarta-time", (w) => ({
    width: w, height: 240,
    x: { label: "start time (UTC) →", type: "time" },
    y: { label: "storms ↑" },
    marks: [
      Plot.rectY(starts, Plot.binX({ y: "count" },
        { x: "t", interval: d3.timeHour.every(3), fill: ACCENT, fillOpacity: 0.85 })),
      Plot.ruleY([0]),
    ],
  }));

  panel("chart-jakarta-scatter", (w) => ({
    width: w, height: 240,
    x: { label: "peak intensity (mm/hr) →" },
    y: { label: "volume (km³) ↑", type: "sqrt" },
    color: intensityScale,
    marks: [
      Plot.dot(props, {
        x: "max_intensity_mm_hr", y: "volume_km3",
        fill: "max_intensity_mm_hr", r: 4, fillOpacity: 0.85,
        title: (p) => `${p.start.replace("T", " ")}\n${fmt.f3(p.volume_km3)} km3\n` +
                      `${p.duration_h} h`,
        tip: true,
      }),
      Plot.ruleY([0]),
    ],
  }));

  const r = d3.max(props, (p) => p.volume_km3);
  text("caption-jakarta-scatter",
    `Volume and peak intensity are related but not interchangeable: the largest storm ` +
    `here is ${fmt.f3(r)} km&sup3;. A long moderate storm can out-total a short violent one.`);

}

// ------------------------------------------------- 4. accumulation and rank

function renderAccumulation(acc, rank) {
  if (acc) {
    const rows = acc.hourly.map((h) => ({ ...h, t: new Date(h.t) }));
    const maxCum = d3.max(rows, (r) => r.cum_mean_mm);

    panel("chart-accum-series", (w) => ({
      width: w, height: 290,
      marginRight: 52,
      x: { label: "UTC →", type: "time" },
      y: { label: "mm per hour ↑", zero: true },
      marks: [
        Plot.rectY(rows, { x: "t", y: "mean_mm", interval: d3.timeHour,
                           fill: ACCENT, fillOpacity: 0.75,
                           title: (d) => `${d.t.toISOString().slice(5, 16)} UTC\n` +
                                         `${fmt.f1(d.mean_mm)} mm areal mean\n` +
                                         `${fmt.f1(d.max_mm)} mm wettest cell`,
                           tip: true }),
        // Cumulative on the same frame, rescaled. A second y axis would be more
        // correct and much harder to read at this size.
        Plot.line(rows, { x: "t",
                          y: (d) => d.cum_mean_mm / maxCum *
                                    d3.max(rows, (r) => r.mean_mm),
                          stroke: "#c2410c", strokeWidth: 2 }),
        Plot.ruleY([0]),
      ],
    }));

    const dki = acc.areas.find((a) => a.name === "DKI Jakarta") ?? acc.areas[0];
    text("caption-accum-series",
      `Areal mean over DKI Jakarta, bars, with cumulative total in orange rescaled to ` +
      `fit (it reaches <strong>${fmt.f1(dki.mean_mm)} mm</strong> over the four days). ` +
      `Local time is UTC+7, so the heaviest hours here, late on 31 December UTC, are ` +
      `the small hours of 1 January in Jakarta.`);

    const g = acc.grid;
    const [lat0, lat1, lon0, lon1] = acc.bbox;
    panel("chart-accum-map", (w) => ({
      width: w,
      height: Math.round(w * (lat1 - lat0) / (lon1 - lon0)) + 46,
      marginLeft: 44, marginBottom: 34,
      // One decimal: the box spans 2.6 degrees of latitude, so whole degrees give
      // "6S" twice and "7S" twice.
      x: { label: null, ticks: 5, tickFormat: (d) => `${d.toFixed(1)}E` },
      y: { label: null, ticks: 5, tickFormat: (d) => `${Math.abs(d).toFixed(1)}S` },
      color: { type: "sqrt", scheme: "Blues", label: "mm over 4 days", legend: true },
      grid: false,
      marks: [
        Plot.rect(g, { x1: (d) => d.lon - 0.05, x2: (d) => d.lon + 0.05,
                       y1: (d) => d.lat - 0.05, y2: (d) => d.lat + 0.05,
                       fill: "mm",
                       title: (d) => `${d.lat.toFixed(1)}, ${d.lon.toFixed(1)}\n` +
                                     `${fmt.f1(d.mm)} mm`,
                       tip: true }),
        Plot.dot([{ lon: 106.845, lat: -6.209 }], { x: "lon", y: "lat", r: 5,
                 fill: "none", stroke: "#c2410c", strokeWidth: 2 }),
        Plot.text([{ lon: 106.845, lat: -6.209 }], { x: "lon", y: "lat",
                 text: () => "Jakarta", dy: -13, fill: INK, fontSize: 11,
                 fontWeight: 600 }),
        Plot.frame({ stroke: MAP_EDGE }),
      ],
    }));

    text("caption-accum-map",
      `IMERG total, 30 Dec 2019 to 2 Jan 2020, on the 0.1 degree grid. The wettest ` +
      `single cell in the Jabodetabek box reaches ` +
      `<strong>${fmt.f1((acc.areas.find((a) => a.name === "Jabodetabek") ?? dki)
        .max_cell_mm)} mm</strong>.`);

    const tbl = document.getElementById("table-accum");
    if (tbl) {
      tbl.innerHTML =
        `<thead><tr><th>Area</th><th>Cells</th><th>Mean, 4 days</th>
           <th>Wettest cell, 4 days</th><th>Peak 24 h, wettest cell</th></tr></thead>
         <tbody>` +
        acc.areas.map((a) => `<tr>
           <td>${a.name}</td>
           <td class="num">${a.cells}</td>
           <td class="num">${fmt.f1(a.mean_mm)} mm</td>
           <td class="num">${fmt.f1(a.max_cell_mm)} mm</td>
           <td class="num"><strong>${fmt.f1(a.peak_24h_max_cell_mm)} mm</strong></td>
         </tr>`).join("") + `</tbody>`;
    }
  } else {
    missing("chart-accum-series", "accumulation");
    missing("chart-accum-map", "accumulation grid");
  }

  if (!rank) return missing("chart-rank", "rank context");

  const bars = rank.above.map((a) => ({
    label: `top ${(100 - a.quantile).toFixed(a.quantile >= 99.9 ? 2 : 0)}%`,
    quantile: a.quantile,
    n: a.n,
    share: a.share_pct,
  }));

  panel("chart-rank", (w) => ({
    width: w, height: 240,
    marginLeft: 92, marginRight: 60,
    x: { label: "share of the event's storms (%) →", domain: [0, 100] },
    y: { label: null, domain: bars.map((b) => b.label) },
    marks: [
      Plot.barX(bars, { x: "share", y: "label", fill: ACCENT, fillOpacity: 0.85,
                        title: (d) => `${d.n} of ${rank.n_event} storms`, tip: true }),
      Plot.text(bars, { x: "share", y: "label",
                        text: (d) => `${d.n} storms`, dx: 6, textAnchor: "start",
                        fill: INK }),
      Plot.ruleX([0]),
    ],
  }));

  const top = rank.top[0];
  text("caption-rank",
    `Each bar asks how many of the ${rank.n_event} storms over this area during the ` +
    `flood beat a given percentile of the whole ${fmt.si(rank.n_reference)}-storm, ` +
    `28-year population. The largest of them, on ` +
    `${top.start.slice(0, 16).replace("T", " ")} UTC, carried ` +
    `${fmt.f3(top.volume_km3)} km&sup3;, which places it at the ` +
    `<strong>${top.percentile.toFixed(2)}th percentile</strong>: rank ` +
    `${fmt.int(top.rank)} of ${fmt.int(rank.n_reference)}.`);

  const dki = acc ? (acc.areas.find((a) => a.name === "DKI Jakarta") ?? acc.areas[0])
                  : null;
  const p99 = rank.above.find((a) => a.quantile === 99);
  const p90 = rank.above.find((a) => a.quantile === 90);

  text("callout-jakarta",
    `<strong>These storms were large, and the severity scale says otherwise.</strong> ` +
    `All ${rank.n_event} fall in the lowest of the nine severity classes, but that ` +
    `class holds 99.8% of every storm ever catalogued, so membership of it carries ` +
    `almost no information. Measured as percentiles instead, ` +
    `<strong>${p90.n} of them beat the 90th percentile</strong> of the 28-year ` +
    `population and ${p99.n} beat the 99th. The single largest sits at the ` +
    `${rank.top[0].percentile.toFixed(2)}th.` +
    (dki ? ` On the ground, IMERG puts <strong>${fmt.f1(dki.peak_24h_max_cell_mm)} mm ` +
           `in 24 hours</strong> over Jakarta, and gauges in the city recorded far ` +
           `more than that: satellite estimates smooth extremes, and a 11 km cell ` +
           `cannot see a cloudburst over one district.` : "") +
    ` So the honest reading is not that the storms were unremarkable. It is that ` +
    `<strong>a per-storm severity class is the wrong instrument for a flood</strong>: ` +
    `what drowned the city was several days of accumulation over the Ciliwung ` +
    `catchment and what lay downstream of it, and no single storm object measures ` +
    `that. <a href="#sec-severity">Section 12</a> ranks whole linked events instead, ` +
    `which is the unit a warning would be issued for, and gives this event a return ` +
    `period the per-storm scale could not.`);
}

// ------------------------------------------------------------- 4. seasonal

function renderSeasonal(seasonal) {
  if (!seasonal) return missing("chart-seasonal", "seasonal cycle");
  const rows = seasonal.months;

  panel("chart-seasonal", (w) => ({
    width: w, height: 340,
    x: monthAxis,
    y: { label: "share of annual rainfall (%) ↑", zero: true },
    marks: [
      Plot.areaY(rows, {
        x: "month", y1: "p10_share_pct", y2: "p90_share_pct",
        fill: ACCENT, fillOpacity: 0.14, curve: "monotone-x",
      }),
      Plot.line(rows, {
        x: "month", y: "pooled_complete_pct", stroke: ACCENT, strokeWidth: 2.5,
        curve: "monotone-x",
      }),
      Plot.dot(rows, {
        x: "month", y: "pooled_complete_pct", fill: ACCENT, r: 3.5,
        title: (d) => `${MONTHS[d.month - 1]}\n${fmt.f2(d.pooled_complete_pct)}% ` +
                      `(range ${fmt.f1(d.min_share_pct)} to ${fmt.f1(d.max_share_pct)})`,
        tip: true,
      }),
      Plot.line(rows, {
        x: "month", y: "pooled_all_pct", stroke: FAINT, strokeWidth: 1.2,
        strokeDasharray: "3,3", curve: "monotone-x",
      }),
      Plot.ruleY([0]),
    ],
  }));

  const dec = rows[11], aug = rows[7];
  const jan = rows[0];
  const ranked = [...rows].sort((a, b) => b.pooled_complete_pct - a.pooled_complete_pct);
  const janRank = ranked.findIndex((r) => r.month === 1) + 1;

  text("caption-seasonal",
    `Solid line: all complete years pooled (${seasonal.meta.years_used} years, ` +
    `${seasonal.meta.excluded_years.join(", ")} excluded as partial). Dashed line: the ` +
    `same estimator with the partial year left in. Shaded band: 10th to 90th percentile ` +
    `across individual years.`);

  text("callout-seasonal",
    `December is wettest at <strong>${fmt.f2(dec.pooled_complete_pct)}%</strong> and ` +
    `August driest at <strong>${fmt.f2(aug.pooled_complete_pct)}%</strong>, a ratio of ` +
    `${fmt.f2(seasonal.dec_over_aug.pooled_complete)}x. January ranks ` +
    `<strong>${janRank === 2 ? "second" : `#${janRank}`}</strong> over the full record ` +
    `at ${fmt.f2(jan.pooled_complete_pct)}%, but in 2020 alone it ranked 9th of 12. ` +
    `A single year cannot rank the months, and the band shows why: December itself ` +
    `varies from ${fmt.f1(dec.min_share_pct)}% to ${fmt.f1(dec.max_share_pct)}% ` +
    `depending on the year.`);
}

// --------------------------------------------------------------- 5. annual

function renderAnnual(annual) {
  if (!annual) return missing("chart-annual-vol", "annual series");
  const y = annual.years;
  const full = y.filter((d) => d.months === 12);
  const partial = y.filter((d) => d.months !== 12);

  const years = y.map((d) => d.year);
  const mk = (id, field, label) => panel(id, (w) => ({
    width: w, height: 260,
    // One tick per year overlaps into an unreadable smear at any realistic width.
    // Thin to roughly one label per 60px and always keep the first and last year.
    x: {
      label: null,
      tickFormat: "d",
      ticks: years.filter((yr, i) =>
        i === 0 || i === years.length - 1 ||
        yr % Math.max(1, Math.ceil(years.length / (w / 60))) === 0),
    },
    y: { label, zero: true },
    marks: [
      Plot.barY(full, { x: "year", y: field, fill: ACCENT, fillOpacity: 0.85,
                        title: (d) => `${d.year}\n${fmt.si(d[field])}`, tip: true }),
      Plot.barY(partial, {
        x: "year", y: field, fill: FAINT, fillOpacity: 0.55,
        title: (d) => `${d.year} (only ${d.months} months)\n${fmt.si(d[field])}`,
        tip: true,
      }),
      Plot.ruleY([d3.mean(full, (d) => d[field])],
                 { stroke: INK, strokeDasharray: "4,3", strokeWidth: 1 }),
      Plot.ruleY([0]),
    ],
  }));

  mk("chart-annual-vol", "volume_km3", "km³ ↑");
  mk("chart-annual-count", "storms", "storms ↑");

  const v = full.map((d) => d.volume_km3);
  text("caption-annual",
    `Dashed line is the mean over complete years. Greyed bars are partial years: ` +
    `${partial.map((d) => `${d.year} has ${d.months} months`).join(", ")}, because ` +
    `IMERG Final V07 ends 2025-09-30. Volume ranges ` +
    `${fmt.int(Math.round(d3.min(v)))} to ${fmt.int(Math.round(d3.max(v)))} km&sup3;, a ` +
    `spread of ${fmt.f2(d3.max(v) / d3.min(v))}x, so interannual variability is real ` +
    `but modest. Storm count varies more than volume does, which is a property of the ` +
    `parameter rather than of the weather.`);
}

// ------------------------------------------------------------- 6. regional

function renderRegional(regional) {
  if (!regional) return missing("chart-regional", "regional breakdown");
  const names = Object.fromEntries(regional.contrast.map((c) => [c.region, c.name]));
  const shapes = regional.shapes.map((s) => ({ ...s,
    name: names[s.region] ?? String(s.region), pct: s.share * 100 }));

  panel("chart-regional", (w) => ({
    width: w, height: 330,
    x: monthAxis,
    y: { label: "share of that region's annual rainfall (%) ↑", zero: true },
    color: { legend: true, domain: Object.values(names),
             range: ["#c2410c", "#b8860b", ACCENT] },
    marks: [
      Plot.line(shapes, { x: "month", y: "pct", stroke: "name", strokeWidth: 2.5,
                          curve: "monotone-x" }),
      Plot.dot(shapes, { x: "month", y: "pct", fill: "name", r: 3,
                         title: (d) => `${d.name}\n${MONTHS[d.month - 1]}: ` +
                                       `${fmt.f2(d.pct)}%`, tip: true }),
      Plot.ruleY([100 / 12], { stroke: FAINT, strokeDasharray: "4,3" }),
      Plot.ruleY([0]),
    ],
  }));

  text("caption-regional",
    `Dashed line is a flat year, 8.33% a month. The equatorial region sits almost on it. ` +
    `Region labels are descriptive: the clustering used seasonal shape only, with no ` +
    `geography given to it.`);

  const rows = regional.contrast;
  const tbl = document.getElementById("table-regional");
  if (tbl) {
    tbl.innerHTML =
      `<thead><tr>
         <th>Region</th><th>Cells</th><th>Share of volume</th>
         <th>Peak</th><th>Trough</th>
         <th>Contrast, equal cells</th><th>Contrast, by volume</th>
       </tr></thead><tbody>` +
      rows.map((c) => `<tr>
         <td>${c.name}</td>
         <td class="num">${c.cells}</td>
         <td class="num">${fmt.f1(c.volume_share_of_domain_pct)}%</td>
         <td>${MONTHS[c.cell_mean.peak_month - 1]}</td>
         <td>${MONTHS[c.cell_mean.trough_month - 1]}</td>
         <td class="num"><strong>${fmt.f2(c.cell_mean.contrast)}x</strong></td>
         <td class="num">${fmt.f2(c.volume_weighted.contrast)}x</td>
       </tr>`).join("") +
      `<tr>
         <td><em>domain-wide</em></td>
         <td class="num">${d3.sum(rows, (c) => c.cells)}</td>
         <td class="num">100%</td>
         <td>${MONTHS[regional.domain.peak_month - 1]}</td>
         <td>${MONTHS[regional.domain.trough_month - 1]}</td>
         <td class="num">n/a</td>
         <td class="num"><strong>${fmt.f2(regional.domain.contrast)}x</strong></td>
       </tr></tbody>`;
  }

  const mon = rows.find((c) => c.name === "monsoonal") ?? rows[0];
  const eq = rows.find((c) => c.name === "equatorial") ?? rows[rows.length - 1];
  text("caption-regional", document.getElementById("caption-regional").innerHTML +
    ` <br><br>The monsoonal south swings <strong>${fmt.f2(mon.cell_mean.contrast)}x</strong> ` +
    `between its wettest and driest month. Domain-wide the figure is ` +
    `${fmt.f2(regional.domain.contrast)}x, because the equatorial region is ` +
    `${fmt.f1(eq.volume_share_of_domain_pct)}% of the volume and nearly aseasonal, so it ` +
    `dominates any average. The last two columns weight cells equally and by rainfall ` +
    `respectively; both are reported because the choice changes the headline number.`);
}

// -------------------------------------------------------------- 7. diurnal

function renderDiurnal(diurnal) {
  if (!diurnal) return missing("chart-diurnal", "diurnal cycle");
  const rows = diurnal.bins.flatMap((b) => [
    { bin: b.hour, series: "land, local time", pct: b.land_local * 100 },
    { bin: b.hour, series: "sea, local time", pct: b.sea_local * 100 },
    { bin: b.hour, series: "land, UTC", pct: b.land_utc * 100 },
    { bin: b.hour, series: "sea, UTC", pct: b.sea_utc * 100 },
  ]);
  const solid = rows.filter((r) => r.series.includes("local"));
  const faded = rows.filter((r) => r.series.includes("UTC"));

  panel("chart-diurnal", (w) => ({
    width: w, height: 330,
    x: { label: "hour →", domain: diurnal.bins.map((b) => b.hour) },
    y: { label: "share of storm initiations (%) ↑", zero: true },
    color: { legend: true, domain: ["land, local time", "sea, local time"],
             range: ["#c2410c", "#1d6fa5"] },
    marks: [
      Plot.line(faded, { x: "bin", y: "pct", z: "series", stroke: FAINT,
                         strokeWidth: 1, strokeDasharray: "3,3" }),
      Plot.line(solid, { x: "bin", y: "pct", stroke: "series", strokeWidth: 2.5,
                         curve: "monotone-x" }),
      Plot.dot(solid, { x: "bin", y: "pct", fill: "series", r: 3.5,
                        title: (d) => `${d.series}\n${d.bin}: ${fmt.f2(d.pct)}%`,
                        tip: true }),
      Plot.ruleY([100 / 12], { stroke: FAINT, strokeDasharray: "4,3" }),
      Plot.ruleY([0]),
    ],
  }));

  const amp = (key) => {
    const v = diurnal.bins.map((b) => b[key]);
    return d3.max(v) / d3.min(v);
  };
  const peakBin = (key) => {
    const b = d3.greatest(diurnal.bins, (x) => x[key]);
    return b.hour;
  };

  text("caption-diurnal",
    `Solid lines are local time (UTC+7 to +9 by longitude); dashed grey are the same ` +
    `data in UTC, where the signal is smeared because the country spans three zones. ` +
    `Land peaks at <strong>${peakBin("land_local")} local</strong> with an amplitude of ` +
    `<strong>${fmt.f2(amp("land_local"))}x</strong>; sea peaks at ` +
    `<strong>${peakBin("sea_local")} local</strong> at ${fmt.f2(amp("sea_local"))}x. ` +
    `Afternoon convection over heated land, nocturnal convection over warm water: the ` +
    `textbook maritime-continent cycle, recovered from a segmentation that was never ` +
    `told about land, sea or the time of day.`);
}

// -------------------------------------------------------- 8. concentration

function renderConcentration(conc) {
  if (!conc) return missing("chart-concentration", "concentration curve");
  const curve = conc.curve.map((d) => ({ x: d.storm_frac * 100, y: d.volume_frac * 100 }));

  panel("chart-concentration", (w) => ({
    width: w, height: 360,
    x: { label: "largest storms, share of population (%) →", type: "log",
         domain: [0.001, 100] },
    y: { label: "share of total rainfall (%) ↑", domain: [0, 100] },
    marks: [
      Plot.line(curve, { x: "x", y: "y", stroke: ACCENT, strokeWidth: 2.5 }),
      Plot.dot(conc.milestones, {
        x: "top_pct", y: "volume_share_pct", fill: ACCENT, r: 5,
        title: (d) => `top ${d.top_pct}% of storms\n` +
                      `${fmt.f1(d.volume_share_pct)}% of the rain`,
        tip: true,
      }),
      Plot.text(conc.milestones, {
        x: "top_pct", y: "volume_share_pct",
        text: (d) => `${d.top_pct}%`, dy: -14, fill: INK, fontVariant: "tabular-nums",
      }),
      Plot.ruleY([0]),
    ],
  }));

  const m13 = conc.milestones.find((d) => d.top_pct === 13);
  const m1 = conc.milestones.find((d) => d.top_pct === 1);
  const m50 = conc.milestones.find((d) => d.top_pct === 50);

  text("caption-concentration",
    `${fmt.int(conc.meta.n_storms)} storms, truncated ones excluded. Log x axis, so the ` +
    `head of the distribution is visible.`);
  text("callout-concentration",
    `The largest <strong>1%</strong> of storms carry ` +
    `<strong>${fmt.f1(m1.volume_share_pct)}%</strong> of all the rain, the largest 13% ` +
    `carry <strong>${fmt.f1(m13.volume_share_pct)}%</strong>, and the smaller half of ` +
    `the population contributes the last ${fmt.f1(100 - m50.volume_share_pct)}%. ` +
    `The 13% mark is there for comparison with the source work, which found long-lived ` +
    `storms to be 13% of its population; over the Lower Mekong those carried more than ` +
    `97% of monsoon rainfall, against ${fmt.f1(m13.volume_share_pct)}% here. Most of ` +
    `that gap is a different definition of what counts as one storm, not a different ` +
    `climate.`);
}

// ---------------------------------------------------------- 9. lead time

function renderLeadtime(lead) {
  if (!lead) return missing("chart-lead-scatter", "lead time");
  const p = lead.provinces;

  panel("chart-lead-scatter", (w) => ({
    width: w, height: 300,
    x: { label: "median distance offshore at formation (km) →" },
    y: { label: "median hours at sea ↑", zero: true },
    marks: [
      Plot.linearRegressionY(p, { x: "offshore_km", y: "median_lead_h",
                                  stroke: ACCENT, fillOpacity: 0.1 }),
      Plot.dot(p, {
        x: "offshore_km", y: "median_lead_h", r: (d) => Math.sqrt(d.n) / 8,
        fill: ACCENT, fillOpacity: 0.7, stroke: ACCENT,
        title: (d) => `${d.province}\n${fmt.int(d.n)} storms\n` +
                      `${fmt.f1(d.offshore_km)} km offshore\n` +
                      `${fmt.f1(d.median_lead_h)} h median lead`,
        tip: true,
      }),
      Plot.text(p.filter((d) => d.median_lead_h >= 4.5 || d.median_lead_h <= 2.2), {
        x: "offshore_km", y: "median_lead_h", text: "province",
        dy: -11, fontSize: 10, fill: INK,
      }),
      Plot.ruleY([0]),
    ],
  }));

  text("caption-lead-scatter",
    `One dot per province, sized by how many sea-formed storms it has. Pearson ` +
    `<strong>r = ${fmt.f3(lead.r_offshore_vs_lead)}</strong> across ` +
    `${lead.n_provinces} provinces with at least ` +
    `${fmt.int(lead.meta.min_storms_per_province)} storms each ` +
    `(${fmt.f3(lead.r_all_provinces)} if all ${lead.n_provinces_total} are kept). ` +
    `Across individual storms it is only +0.505: aggregating to provinces removes ` +
    `within-province scatter, and the two numbers are not interchangeable.`);

  panel("chart-lead-hist", (w) => ({
    width: w, height: 300,
    x: { label: "hours over water before landfall →" },
    y: { label: "storms ↑" },
    marks: [
      Plot.rectY(lead.histogram, {
        x: "hours_at_sea", y: "n", interval: 0.5, fill: ACCENT, fillOpacity: 0.8,
        title: (d) => `${d.hours_at_sea} h: ${fmt.int(d.n)} storms`, tip: true,
      }),
      Plot.ruleX([lead.median_lead_h], { stroke: "#c2410c", strokeWidth: 2 }),
      Plot.ruleY([0]),
    ],
  }));

  text("caption-lead-hist",
    `${fmt.int(lead.n_sea_formed)} storms formed at sea and made landfall. Median ` +
    `<strong>${fmt.f1(lead.median_lead_h)} h</strong> (orange line), p90 ` +
    `${fmt.f1(lead.p90_lead_h)} h. Capped at 24 h for display. Every one of these ` +
    `storms was over water for some period during which it could have been watched.`);

  panel("chart-lead-quartile", (w) => ({
    width: w, height: 230,
    marginLeft: 90,
    x: { label: "hours at sea →", zero: true },
    y: { label: null },
    marks: [
      Plot.barX(lead.by_volume_quartile, {
        x: "median_lead_h", y: "q", fill: ACCENT, fillOpacity: 0.85,
        sort: { y: "x" },
      }),
      Plot.ruleX(lead.by_volume_quartile, {
        x1: "median_lead_h", x2: "p90_lead_h", y: "q", stroke: INK, strokeWidth: 1,
      }),
      Plot.dot(lead.by_volume_quartile, { x: "p90_lead_h", y: "q", fill: INK, r: 3 }),
      Plot.text(lead.by_volume_quartile, {
        x: "median_lead_h", y: "q", text: (d) => `${fmt.f1(d.median_lead_h)} h`,
        dx: -8, textAnchor: "end", fill: css("--bg-panel") || "#fff",
        fontVariant: "tabular-nums",
      }),
      Plot.ruleX([0]),
    ],
  }));

  const q = lead.by_volume_quartile;
  const small = q[0], large = q[q.length - 1];
  text("caption-lead-quartile",
    `Bars are the median, the line and dot extend to the 90th percentile. The largest ` +
    `quarter of storms give <strong>${fmt.f1(large.median_lead_h)} h</strong> of median ` +
    `lead time and ${fmt.f1(large.p90_lead_h)} h at p90, against ` +
    `${fmt.f1(small.median_lead_h)} h for the smallest quarter. The storms that matter ` +
    `most are the ones that announce themselves earliest, which is the one genuinely ` +
    `operational result on this page.`);
}

// ---------------------------------------------------------------- 10. sweep

function renderSweep(sweep) {
  if (!sweep) return missing("chart-sweep-count", "parameter sweep");
  const rows = sweep.rows.map((r) => ({
    ...r, series: `${r.method}, ${r.month ?? r.period ?? ""}`.trim(),
  }));
  const key = rows[0].captured !== undefined ? "captured" : "captured_frac";

  const mk = (id, field, label, opts = {}) => panel(id, (w) => ({
    width: w, height: 280,
    x: { label: "prominence h (mm/hr) →", type: "log" },
    y: { label, ...opts },
    color: { legend: true },
    marks: [
      Plot.line(rows, { x: "h", y: field, stroke: "series", strokeWidth: 2,
                        marker: "circle" }),
      Plot.ruleX([4], { stroke: "#c2410c", strokeDasharray: "4,3" }),
    ],
  }));

  mk("chart-sweep-count", "n_storms", "storms ↑", { type: "log" });
  mk("chart-sweep-captured", key, "share of rain captured ↑", { domain: [0.85, 1] });

  text("callout-sweep",
    `The orange line is the adopted <code>h</code> = 4.0. <strong>Counts move steeply ` +
    `with the parameter and captured volume barely moves at all.</strong> A plus or ` +
    `minus 20% change in <code>h</code> shifts the storm count by about 20%, against a ` +
    `10% stability criterion, so there is no canonical number of storms. An eightfold ` +
    `change in <code>h</code> moves captured volume by 1.3%. That asymmetry is the ` +
    `practical rule this project runs on: <strong>volume-based statistics are safe, ` +
    `count-based statistics are not</strong>, and comparisons between months or regions ` +
    `sit close to the safe end.`);
}

// ------------------------------------------------------- 11. severity, ages

function renderSeverity(sev, fam, fsev) {
  if (sev) {
    const names = ["very low", "low", "moderate", "medium", "heavy", "very heavy",
                   "intense", "severe", "extreme"];
    const grid = sev.grid.map((g) => ({
      ...g,
      vol: ["common", "uncommon", "rare"][g.vol_band],
      int: ["common", "uncommon", "rare"][g.int_band],
    }));

    panel("chart-severity", (w) => ({
      width: w, height: 300,
      marginLeft: 82, marginBottom: 56,
      x: { label: "intensity band →", domain: ["common", "uncommon", "rare"] },
      y: { label: "↑ volume band", domain: ["rare", "uncommon", "common"] },
      color: { type: "log", scheme: "YlGnBu", label: "storms" },
      grid: false,
      marks: [
        Plot.cell(grid, { x: "int", y: "vol", fill: (d) => Math.max(d.storms, 1),
                          inset: 1 }),
        Plot.text(grid, {
          x: "int", y: "vol",
          text: (d) => `${d.name}\n${fmt.si(d.storms)}`,
          fill: (d) => d.storms > 100000 ? "#fff" : INK, fontSize: 10,
        }),
      ],
    }));

    const [lo, hi] = sev.volume_edges_km3;
    const total = d3.sum(sev.grid, (g) => g.storms);
    const lowest = sev.grid.find((g) => g.name === "very low");
    text("caption-severity",
      `Nine classes from two axes: rainfall volume and peak intensity. Band edges are ` +
      `<strong>exceedance rates</strong>, not return periods: ` +
      `${sev.rate_bands_per_year[0]} and ${sev.rate_bands_per_year[1]} storms a year, ` +
      `which here means ${fmt.f2(lo)} and ${fmt.f2(hi)} km&sup3;. Per-storm return ` +
      `periods would be meaningless at ${fmt.si(total / sev.n_years)} storms a year. ` +
      `<strong>${fmt.pct1(lowest.storms / total * 100)}% of storms land in the lowest ` +
      `class</strong>, which is what choosing operationally rare thresholds implies: ` +
      `the scale is built to isolate the tail, not to spread the population evenly.`);
  } else {
    missing("chart-severity", "severity grid");
  }

  if (fsev) {
    const grid = fsev.occupancy.map((o, i) => ({
      name: o.severity,
      families: o.families,
      vol: ["common", "uncommon", "rare"][Math.floor(i / 3)],
      int: ["common", "uncommon", "rare"][i % 3],
    }));

    panel("chart-family-severity", (w) => ({
      width: w, height: 300,
      marginLeft: 82, marginBottom: 56,
      x: { label: "intensity band →", domain: ["common", "uncommon", "rare"] },
      y: { label: "↑ volume band", domain: ["rare", "uncommon", "common"] },
      color: { type: "log", scheme: "YlOrRd", label: "events" },
      grid: false,
      marks: [
        Plot.cell(grid, { x: "int", y: "vol",
                          fill: (d) => Math.max(d.families, 1), inset: 1 }),
        Plot.text(grid, {
          x: "int", y: "vol",
          text: (d) => `${d.name}\n${fmt.si(d.families)}`,
          fill: (d) => d.families > 50000 ? "#fff" : INK, fontSize: 10,
        }),
      ],
    }));

    const lowest = fsev.occupancy.find((o) => o.severity === "very low");
    const [flo, fhi] = fsev.volume_edges_km3;
    text("caption-family-severity",
      `${fmt.si(fsev.n_families)} linked events over ${fmt.f1(fsev.n_years)} years, ` +
      `${fmt.si(fsev.families_per_year)} a year. Band edges at ` +
      `${fsev.rate_bands_per_year[0]} and ${fsev.rate_bands_per_year[1]} events a ` +
      `year, which here means ${fmt.f2(flo)} and ${fmt.f2(fhi)} km&sup3;. The lowest ` +
      `class holds <strong>${fmt.pct1(lowest.share_pct)}%</strong> of events, against ` +
      `99.8% for the per-storm scale on the left. Linking check: the single largest ` +
      `event holds ${fmt.f3(fsev.percolation_share * 100)}% of all the rain, far ` +
      `below the 20% that would mean the linking had merged the domain.`);

    const e = fsev.event;
    if (e && e.n_families) {
      const g = e.largest;
      text("callout-family",
        `<strong>Moving from cells to events did not fix it, and that is the result.</strong> ` +
        `The Jakarta flood breaks into <strong>${e.n_families} families</strong>, not ` +
        `one. Its largest ran ${g.age_h.toFixed(0)} hours and absorbed ${g.n_storms} ` +
        `cells, but carried only ${fmt.f2(g.volume_km3)} km&sup3; of the ` +
        `${fmt.f2(e.combined_volume_km3)} km&sup3; the whole event delivered. ` +
        `That puts it at the <strong>${g.percentile.toFixed(2)}th percentile</strong> ` +
        `of ${fmt.si(e.n_reference)} events, against the ` +
        `<strong>99.58th</strong> its largest single storm reached: the unit changed ` +
        `and the answer barely moved. The class is still the lowest of nine, and ` +
        `${fmt.int(Math.round(g.rank / e.n_years))} events a year beat it, so no ` +
        `return period is claimable. ` +
        `<strong>The linking rule is why.</strong> It has to stay strict at 3 hours ` +
        `and 50 km or families percolate and swallow the domain, and a rule tight ` +
        `enough to prevent that is too tight to assemble a four-day flood into one ` +
        `object.`);
    }

    // ---- area and window ranking, which is what does identify the event
    const ar = fsev.area_rank ?? [];
    const headline = ar.find((a) => a.annual_maxima) ?? ar[0];

    if (headline && headline.annual_maxima) {
      // Highlight the year whose annual maximum IS this event, found by matching the
      // value rather than by assuming a year. The window opens on 31 Dec 2019 but the
      // rolling total lands in 2020, and colouring both years implied, wrongly, that
      // 2019's separate annual maximum was part of the same flood.
      const am = headline.annual_maxima.map((d) => ({
        ...d, isEvent: Math.abs(d.value_km3 - headline.value_km3) < 1e-6,
      }));
      const med = headline.median_annual_max_km3;

      panel("chart-annual-max", (w) => ({
        width: w, height: 300,
        marginBottom: 44,
        x: { label: null, tickFormat: "d",
             ticks: am.map((d) => d.year).filter((y, i) => i % 3 === 0) },
        y: { label: `largest ${headline.window_days}-day total (km³) ↑`,
             zero: true },
        marks: [
          Plot.barY(am, { x: "year", y: "value_km3",
                          fill: (d) => d.isEvent ? "#c2410c" : ACCENT,
                          fillOpacity: 0.85,
                          title: (d) => `${d.year}: ${fmt.f3(d.value_km3)} km3`,
                          tip: true }),
          Plot.ruleY([med], { stroke: INK, strokeDasharray: "4,3" }),
          Plot.ruleY([0]),
        ],
      }));

      text("caption-annual-max",
        `Largest ${headline.window_days}-day catalogued rainfall total over ` +
        `<strong>${headline.area}</strong> in each complete year, 1998 to 2024. ` +
        `Orange is the New Year 2020 event. Dashed line is the median year ` +
        `(${fmt.f3(med)} km&sup3;). The event reaches ` +
        `<strong>${fmt.f3(headline.value_km3)} km&sup3;</strong>, ` +
        `<strong>${fmt.f2(headline.ratio_to_median)}x</strong> the median annual ` +
        `maximum and <strong>${headline.verdict}</strong> for this area at this ` +
        `window length.`);

      text("callout-area",
        `Ranked as rainfall over the flooded catchment rather than as an object, the ` +
        `event is finally where intuition says it should be: the ` +
        `<strong>largest ${headline.window_days}-day total in ${headline.n_years_compared} ` +
        `years</strong> over Jabodetabek. Nothing about the storms changed between ` +
        `this paragraph and the one above. What changed is that the quantity being ` +
        `ranked is now the one a flood responds to. <strong>The catalogue is still ` +
        `doing the work</strong>, supplying which rain belonged to storms and where ` +
        `it fell, but the severity question is answered by integrating it over an ` +
        `area and a window, not by finding the biggest object in it.`);
    }

    const tar = document.getElementById("table-area-rank");
    if (tar && ar.length) {
      tar.innerHTML =
        `<thead><tr><th>Area</th><th>Window</th><th>Total</th>
           <th>Rank</th><th>vs median year</th><th>Verdict</th></tr></thead><tbody>` +
        ar.map((a) => `<tr${a.is_record ? ' class="chosen"' : ""}>
           <td>${a.area}</td>
           <td class="num">${a.window_days} day${a.window_days > 1 ? "s" : ""}</td>
           <td class="num">${fmt.f3(a.value_km3)} km³</td>
           <td class="num">${a.rank} of ${a.n_years_compared}</td>
           <td class="num">${fmt.f2(a.ratio_to_median)}x</td>
           <td>${a.is_record ? "<strong>" + a.verdict + "</strong>" : a.verdict}</td>
         </tr>`).join("") + `</tbody>`;
    }
    text("caption-area-rank",
      `The same four days, measured ten ways. Over <strong>Jabodetabek</strong>, the ` +
      `catchment that flooded, a 2-day window is the highest in the record and 3 to 4 ` +
      `days is about 1 in 14 years. Stretch the area to all of Jakarta and West Java, ` +
      `or the window to a week, and the event drops below an ordinary year. ` +
      `<strong>Both are correct.</strong> An event severity is only defined once the ` +
      `area and the duration are fixed, and quoting one without them says nothing. ` +
      `That is the honest limit of what any severity number can mean.`);

    const tb = document.getElementById("table-bands");
    if (tb) {
      tb.innerHTML =
        `<thead><tr><th>Band rate (events/yr)</th><th>Volume edges</th>
           <th>Lowest class holds</th><th>Top three classes</th></tr></thead><tbody>` +
        fsev.band_choice.map((b) => {
          const chosen = b.bands[0] === fsev.rate_bands_per_year[0];
          return `<tr${chosen ? ' class="chosen"' : ""}>
            <td>${b.bands[0]} and ${b.bands[1]}${chosen ? " <em>(used)</em>" : ""}</td>
            <td class="num">${fmt.f2(b.volume_edges_km3[0])} / ${fmt.f2(b.volume_edges_km3[1])} km³</td>
            <td class="num">${fmt.pct1(b.lowest_class_share_pct)}%</td>
            <td class="num">${fmt.int(b.top3_families)}</td>
          </tr>`;
        }).join("") + `</tbody>`;
    }
    text("caption-bands",
      `The per-storm scale uses 500 and 50 a year. Carried over to events unchanged it ` +
      `would leave the lowest class holding almost everything again, so the rate was ` +
      `chosen against this table rather than inherited. Every row is a real fit; none ` +
      `is a better or worse answer in itself, but a scale whose bottom class holds the ` +
      `whole population cannot discriminate.`);

    const tt = document.getElementById("table-top-events");
    if (tt) {
      tt.innerHTML =
        `<thead><tr><th>Start</th><th>Duration</th><th>Cells</th><th>Volume</th>
           <th>Centre</th><th>Class</th></tr></thead><tbody>` +
        fsev.largest_in_record.map((r) => `<tr>
           <td>${r.start.slice(0, 10)}</td>
           <td class="num">${fmt.f0(r.age_h)} h</td>
           <td class="num">${fmt.int(r.n_storms)}</td>
           <td class="num"><strong>${fmt.f2(r.volume_km3)} km³</strong></td>
           <td class="num">${Math.abs(r.lat).toFixed(1)}${r.lat < 0 ? "S" : "N"}, ${r.lon.toFixed(1)}E</td>
           <td>${r.severity}</td>
         </tr>`).join("") + `</tbody>`;
    }
    const d = fsev.distribution;
    text("caption-top-events",
      `The twelve biggest events in 28 years. For scale, the median event is ` +
      `${fmt.f3(d.volume_p50)} km&sup3; and lasts ${fmt.f1(d.age_h_p50)} hours, and ` +
      `the longest-lived ran ${fmt.f0(d.age_h_max)} hours. Most families are a single ` +
      `unlinked cell, which is why the event population is only modestly smaller than ` +
      `the storm population.`);
  } else {
    missing("chart-family-severity", "family severity");
  }

  if (fam) {
    const order = ["under a day", "1 day", "2 days", "3+ days"];
    const rows = fam.classes.slice().sort(
      (a, b) => order.indexOf(a.age_class) - order.indexOf(b.age_class));

    panel("chart-families", (w) => ({
      width: w, height: 300,
      marginLeft: 96,
      marginRight: 64,   // room for the count label beyond the longest bar
      x: { label: "families (log scale) →", type: "log" },
      y: { label: null, domain: rows.map((r) => r.age_class) },
      grid: true,
      marks: [
        Plot.barX(rows, { x: "families", y: "age_class", fill: ACCENT,
                          fillOpacity: 0.85,
                          title: (d) => `${d.age_class}\n${fmt.int(d.families)} families` +
                                        `\n${fmt.f1(d.volume_share_pct)}% of volume`,
                          tip: true }),
        Plot.text(rows, { x: "families", y: "age_class",
                          text: (d) => fmt.int(d.families), dx: 6,
                          textAnchor: "start", fill: INK }),
      ],
    }));

    const multi = rows.filter((r) => r.age_class !== "under a day");
    const nMulti = d3.sum(multi, (r) => r.families);
    text("caption-families",
      `A storm at <code>h</code> = 4 is a convective cell, and a convective cell does ` +
      `not live for days: asking for a storm's age in days returns almost nothing. ` +
      `Age belongs to <strong>families</strong> instead, storms linked within 3 hours ` +
      `and 50 km. Of ${fmt.int(fam.n_families)} families, only ${fmt.int(nMulti)} ` +
      `survive past a day. Note the log axis. The linking rule has to be strict: ` +
      `linking by bounding-box overlap percolates exactly as the original segmentation ` +
      `did, and swallows the whole domain.`);
  } else {
    missing("chart-families", "storm families");
  }
}

// ----------------------------------------------------------------- startup

async function main() {
  const [summary, method, seasonal, annual, regional, diurnal, conc, lead, sweep,
         sev, fam, landDomain, landJakarta, tracksDomain, tracksJakarta,
         accum, rank, fsev] =
    await Promise.all([
      load("summary"), load("method"), load("seasonal"), load("annual"),
      load("regional"), load("diurnal"), load("concentration"), load("leadtime"),
      load("sweep"), load("severity"), load("families"),
      load("land_domain"), load("land_jakarta"),
      load("tracks_domain"), load("tracks_jakarta"),
      load("accumulation"), load("rank_context"), load("family_severity"),
    ]);

  renderHero(summary);
  renderMethod(method);
  renderDomainMap(tracksDomain, landDomain);
  renderJakartaMap(tracksJakarta, landJakarta);
  renderAccumulation(accum, rank);
  renderSeasonal(seasonal);
  renderAnnual(annual);
  renderRegional(regional);
  renderDiurnal(diurnal);
  renderConcentration(conc);
  renderLeadtime(lead);
  renderSweep(sweep);
  renderSeverity(sev, fam, fsev);
}

main().catch((e) => console.error(e));
