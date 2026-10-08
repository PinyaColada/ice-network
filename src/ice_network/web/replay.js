/* Data and 2D views. No API calls: this file reads only the embedded evaluator ledger. */
(() => {
  "use strict";
  const data = JSON.parse(document.getElementById("replay-data").textContent);
  const $ = (id) => document.getElementById(id);
  const number = (n, digits = 0) =>
    Number(n).toLocaleString("en-GB", { maximumFractionDigits: digits });
  const money = (n) => "€" + number(n);
  const names = {
    "naive/none": "Last-week average",
    "median/seasonal": "P50 · seasonal",
    "quantile/seasonal": "P95 · seasonal",
    "optimizer/seasonal": "Optimizer · seasonal",
    "median/hurdle": "P50 · hurdle",
    "quantile/hurdle": "P95 · hurdle",
    "optimizer/hurdle": "Optimizer · hurdle",
  };
  for (const name of Object.keys(names))
    if (name.startsWith("quantile/")) {
      names[name] = `P${Math.round(data.config.service * 100)} · ${name.split("/")[1]}`;
    }
  for (const run of Object.values(data.runs)) {
    run.rows = run.rows.map((row) =>
      Object.fromEntries(data.fields.map((name, i) => [name, row[i]])),
    );
    run.byDay = Object.groupBy(run.rows, (row) => row.day);
    run.byBar = Object.groupBy(run.rows, (row) => row.bar);
  }
  const state = {
    run: data.runs["quantile/seasonal"] ? "quantile/seasonal" : Object.keys(data.runs)[0],
    index: 0,
    bar: 0,
    view: "3d",
    visitors: 20,
    timer: null,
    scene: null,
  };
  const run = () => data.runs[state.run];
  const day = () => data.days[state.index];
  const rows = () => run().byDay[day()];
  const row = () => rows().find((r) => r.bar === state.bar);
  const date = (d, short = false) => {
    const t = new Date(data.config.start + "T12:00:00Z");
    t.setUTCDate(t.getUTCDate() + d);
    return t.toLocaleDateString("en-GB", {
      day: "numeric",
      month: short ? "short" : "long",
      timeZone: "UTC",
    });
  };
  const town = (b) => b.name.split(":")[0];
  const esc = (s) =>
    String(s).replace(
      /[&<>"']/g,
      (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
    );
  // Hand-simplified coastline, for orientation only. Geography uses a local equirectangular projection.
  const coast = [
    [2.35, 39.58],
    [2.37, 39.63],
    [2.47, 39.69],
    [2.61, 39.77],
    [2.7, 39.82],
    [2.82, 39.89],
    [2.94, 39.92],
    [3.06, 39.96],
    [3.2, 39.96],
    [3.16, 39.9],
    [3.08, 39.88],
    [3.11, 39.85],
    [3.2, 39.87],
    [3.24, 39.82],
    [3.17, 39.8],
    [3.16, 39.75],
    [3.3, 39.75],
    [3.35, 39.79],
    [3.44, 39.78],
    [3.47, 39.72],
    [3.42, 39.66],
    [3.4, 39.59],
    [3.34, 39.51],
    [3.29, 39.43],
    [3.26, 39.36],
    [3.19, 39.31],
    [3.06, 39.27],
    [3.0, 39.31],
    [2.97, 39.35],
    [2.91, 39.36],
    [2.84, 39.36],
    [2.77, 39.38],
    [2.75, 39.46],
    [2.75, 39.5],
    [2.7, 39.54],
    [2.63, 39.55],
    [2.57, 39.51],
    [2.54, 39.47],
    [2.48, 39.48],
    [2.45, 39.52],
    [2.4, 39.53],
  ];
  const projection = (lon, lat) => [(lon - 2.9) * 0.77 * 100, (39.62 - lat) * 100];
  const activeOrders = () => run().orders.filter((o) => o.departure <= day() && o.arrival >= day());
  function selectBar(b) {
    state.bar = Number(b);
    $("bar").value = state.bar;
    render();
  }
  function selectRun(name) {
    state.run = name;
    $("policy").value = name;
    render();
  }
  function selectDay(index) {
    state.index = Math.max(0, Math.min(data.days.length - 1, Number(index)));
    render();
  }
  function stop() {
    clearInterval(state.timer);
    state.timer = null;
    $("play").textContent = "Play";
    $("play").setAttribute("aria-label", "Play season");
  }
  function play() {
    stop();
    if (state.index === data.days.length - 1) state.index = 0;
    $("play").textContent = "Pause";
    $("play").setAttribute("aria-label", "Pause season");
    render();
    state.timer = setInterval(
      () => {
        if (state.index === data.days.length - 1) return stop();
        selectDay(state.index + 1);
      },
      Number($("speed").value),
    );
  }
  function setView(view) {
    state.view = view;
    $("workspace").className = `workspace mode-${view}`;
    for (const v of ["2d", "3d"]) {
      $(`view-${v}`).classList.toggle("active", v === view);
      $(`view-${v}`).setAttribute("aria-pressed", v === view);
    }
    $("map-title").textContent =
      view === "3d" ? "An island of little freezers" : "Twelve bars. Two ice depots.";
    $("map-help").textContent =
      view === "3d"
        ? "Drag to orbit · scroll to zoom · select a bar"
        : "Select a bar to inspect its season";
    if (state.scene) state.scene.resize();
    renderMap();
  }
  function renderMap() {
    const xy = (p) => {
      const [x, z] = projection(p.lon, p.lat);
      return [380 + x * 6, 235 + z * 4.5];
    };
    const path =
      coast.map(([lon, lat], i) => (i ? "L" : "M") + xy({ lon, lat }).join(",")).join(" ") + "Z";
    let html = `<rect width="760" height="470" fill="#eaf1e9"/><path d="${path}" fill="#d7dcc1" stroke="#b1c5ab" stroke-width="2"/>`;
    for (const o of activeOrders()) {
      const a = xy(data.depots[o.depot]),
        b = xy(data.bars[o.bar]);
      html += `<path d="M${a} Q${(a[0] + b[0]) / 2},${Math.min(a[1], b[1]) - 24} ${b}" fill="none" stroke="#b89147" stroke-width="${o.bar === state.bar ? 2.5 : 1}" stroke-dasharray="4 4" opacity=".65"/>`;
    }
    for (const d of data.depots) {
      const [x, y] = xy(d);
      html += `<rect x="${x - 6}" y="${y - 6}" width="12" height="12" rx="2" fill="#ad873c"/><text x="${x + 12}" y="${y - 8}" font-size="10" fill="#75592c">${esc(d.name)} depot</text>`;
    }
    for (const r of rows()) {
      const b = data.bars[r.bar],
        [x, y] = xy(b),
        lost = r.latent_demand - r.sales;
      html += `<g data-bar="${r.bar}" tabindex="0" role="button" aria-label="${esc(b.name)}"><circle cx="${x}" cy="${y}" r="${9 + (8 * r.closing) / b.capacity}" fill="${lost > 0 ? "#c6653b" : "#177977"}" opacity=".9" stroke="${r.bar === state.bar ? "#fff" : "#eaf1e9"}" stroke-width="${r.bar === state.bar ? 4 : 2}"/><text x="${x}" y="${y + 3}" text-anchor="middle" font-size="9" fill="white">${r.bar + 1}</text><text x="${x + 20}" y="${y + 5}" font-size="10" fill="#344c47">${esc(town(b))}</text></g>`;
    }
    $("map").innerHTML = html;
    $("map")
      .querySelectorAll("[data-bar]")
      .forEach((g) => {
        g.onclick = () => selectBar(g.dataset.bar);
        g.onkeydown = (e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            selectBar(g.dataset.bar);
          }
        };
      });
  }
  function chart(id, series, lines, options = {}) {
    const W = Math.max(280, $(id).clientWidth),
      H = 178,
      L = 43,
      R = 10,
      T = 10,
      B = 26,
      innerW = W - L - R,
      innerH = H - T - B;
    const vals = series
      .flatMap((r) => lines.map((l) => l.value(r)).concat(options.band ? options.band(r) : []))
      .filter((v) => v !== null && Number.isFinite(v));
    const max = Math.max(1, ...vals, options.capacity || 0) * 1.09;
    const x = (i) => L + (i / Math.max(1, series.length - 1)) * innerW,
      y = (v) => H - B - (v / max) * innerH;
    let html = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(options.title || id)}">`;
    for (let i = 0; i <= 3; i++) {
      const v = (max * i) / 3;
      html += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" stroke="#edf0e9"/><text x="${L - 7}" y="${y(v) + 3}" text-anchor="end" font-size="9" fill="#71837b">${number(v)}</text>`;
    }
    for (const i of [
      0,
      Math.floor(series.length / 3),
      Math.floor((series.length * 2) / 3),
      series.length - 1,
    ])
      html += `<text x="${x(i)}" y="${H - 4}" text-anchor="${i === 0 ? "start" : i === series.length - 1 ? "end" : "middle"}" font-size="9" fill="#71837b">${date(series[i].day, true)}</text>`;
    if (options.band && series.every((r) => options.band(r).every((v) => v !== null))) {
      const points = series
        .map((r, i) => `${x(i)},${y(options.band(r)[1])}`)
        .concat(series.map((r, i) => `${x(i)},${y(options.band(r)[0])}`).reverse());
      html += `<polygon points="${points.join(" ")}" fill="#e5ddee" opacity=".75"/>`;
    }
    if (options.capacity)
      html += `<line x1="${L}" x2="${W - R}" y1="${y(options.capacity)}" y2="${y(options.capacity)}" stroke="#748378" stroke-dasharray="5 4"/>`;
    for (const line of lines) {
      if (series.some((r) => line.value(r) === null)) continue;
      if (line.bars) {
        const width = Math.max(1, (innerW / series.length) * 0.6);
        for (const [i, r] of series.entries())
          html += `<rect x="${x(i) - width / 2}" y="${y(line.value(r))}" width="${width}" height="${Math.max(0, y(0) - y(line.value(r)))}" fill="${line.color}" opacity=".45"/>`;
        continue;
      }
      const points = series.map((r, i) => `${x(i)},${y(line.value(r))}`).join(" ");
      if (line.area)
        html += `<polygon points="${x(0)},${y(0)} ${points} ${x(series.length - 1)},${y(0)}" fill="${line.color}" opacity=".08"/>`;
      html += `<polyline points="${points}" fill="none" stroke="${line.color}" stroke-width="${line.width || 1.5}" ${line.dash ? `stroke-dasharray="${line.dash}"` : ""}/>`;
      const selected = series[state.index];
      html += `<circle cx="${x(state.index)}" cy="${y(line.value(selected))}" r="3" fill="${line.color}" stroke="white" stroke-width="1"/>`;
    }
    html += `<line class="cursor-line" x1="${x(state.index)}" x2="${x(state.index)}" y1="${T}" y2="${H - B}"/><rect class="hit-zone" x="${L}" y="0" width="${innerW}" height="${H - B}" fill="transparent"/></svg>`;
    $(id).innerHTML = html;
    const svg = $(id).querySelector("svg");
    svg.querySelector(".hit-zone").onclick = (e) => {
      const box = svg.getBoundingClientRect();
      selectDay(
        Math.round(((((e.clientX - box.left) * W) / box.width - L) / innerW) * (series.length - 1)),
      );
    };
  }
  function renderCharts() {
    const series = run().byBar[state.bar],
      r = row();
    chart(
      "forecast-chart",
      series,
      [
        { value: (r) => r.latent_demand, color: "#47554e", dash: "4 3" },
        { value: (r) => r.sales, color: "#177977", width: 2 },
        { value: (r) => r.p50, color: "#8170a2" },
        { value: (r) => r.p95, color: "#8170a2", dash: "2 4" },
      ],
      { band: (r) => [r.p10, r.p90], title: "Daily demand, sales and quantile forecasts" },
    );
    $("forecast-status").textContent = r.p50 === null ? "Naive: no forecast" : "Same-day forecasts";
    $("forecast-readout").textContent =
      `${date(day(), true)} · demand ${number(r.latent_demand)} · sold ${number(r.sales)}${r.p50 === null ? " · forecast unavailable" : ` · P50 ${number(r.p50)} · P95 ${number(r.p95)}`}`;
    chart(
      "inventory-chart",
      series,
      [
        { value: (r) => r.receipts, color: "#82aca2", bars: true },
        { value: (r) => r.closing, color: "#177977", area: true, width: 2 },
        { value: (r) => r.melt, color: "#c6653b" },
      ],
      {
        capacity: data.bars[state.bar].capacity,
        title: "Closing stock, receipts, melting and storage capacity",
      },
    );
    $("inventory-readout").textContent =
      `${date(day(), true)} · closing ${number(r.closing, 1)} · received ${number(r.receipts)} · melted ${number(r.melt, 1)} bags`;
    chart(
      "customer-chart",
      series,
      [
        { value: (r) => r.latent_demand * state.visitors, color: "#47554e", dash: "4 3" },
        { value: (r) => r.sales * state.visitors, color: "#177977", area: true, width: 2 },
      ],
      { title: "Estimated visitor equivalents, not simulated people" },
    );
    $("customer-readout").textContent =
      `${date(day(), true)} · demand equivalent ${number(r.latent_demand * state.visitors)} · served equivalent ${number(r.sales * state.visitors)} · unserved equivalent ${number((r.latent_demand - r.sales) * state.visitors)}`;
  }
  function render() {
    const selected = row(),
      all = rows(),
      sum = (field) => all.reduce((s, r) => s + r[field], 0);
    const demand = sum("latent_demand"),
      sales = sum("sales"),
      lost = demand - sales;
    $("timeline").value = state.index;
    $("date").textContent = date(day());
    $("day-label").textContent = `Day ${state.index + 1} / ${data.days.length}`;
    $("previous").disabled = state.index === 0;
    $("next").disabled = state.index === data.days.length - 1;
    $("temperature").textContent = number(all[0].temperature, 1) + "°C";
    $("stock-kpi").textContent = number(sum("closing"));
    $("sales-kpi").textContent = number(sales);
    $("demand-kpi").textContent = `of ${number(demand)} bags demanded`;
    $("lost-kpi").textContent = number(lost);
    $("service-kpi").textContent = demand
      ? `${number((sales / demand) * 100, 1)}% daily fill rate`
      : "No demand today";
    $("bars-kpi").textContent = `${all.filter((r) => r.receipts > 0).length} / ${data.bars.length}`;
    $("deliveries-kpi").textContent = `Bars receiving ice · ${number(sum("receipts"))} bags`;
    $("melt-kpi").textContent = number(sum("melt"), 1);
    const b = data.bars[state.bar],
      shortage = selected.latent_demand - selected.sales;
    $("bar-stock").textContent = `${number(selected.closing, 1)} / ${b.capacity} bags`;
    $("capacity-fill").style.width = (selected.closing / b.capacity) * 100 + "%";
    $("capacity-fill").style.background = shortage ? "var(--rust)" : "var(--teal)";
    $("bar-badge").textContent =
      `${shortage ? `${number(shortage)} bags of lost demand` : "All demand served"} · ${selected.event === "none" ? "ordinary day" : selected.event + " day"}`;
    const pipeline = run()
      .orders.filter((o) => o.bar === state.bar && o.departure <= day() && o.arrival > day())
      .reduce((s, o) => s + o.bags, 0);
    $("bar-facts").innerHTML = [
      ["Demand / sold", `${number(selected.latent_demand)} / ${number(selected.sales)}`],
      ["Received today", `${number(selected.receipts)} bags`],
      ["Melted today", `${number(selected.melt, 1)} bags`],
      ["In transit at close", `${number(pipeline)} bags`],
      ["Visitor equivalents", `${number(selected.latent_demand * state.visitors)} est.`],
    ]
      .map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`)
      .join("");
    $("bar-list").innerHTML = data.bars
      .map((b) => {
        const r = all[b.id];
        return `<button data-bar="${b.id}" class="${b.id === state.bar ? "active" : ""}" aria-pressed="${b.id === state.bar}">${b.id + 1}. ${esc(town(b))}<i class="${r.sales < r.latent_demand ? "empty" : ""}"></i></button>`;
      })
      .join("");
    $("bar-list")
      .querySelectorAll("button")
      .forEach((el) => (el.onclick = () => selectBar(el.dataset.bar)));
    const departures = run().orders.filter((o) => o.departure === day()),
      totalTrips = departures.reduce((s, o) => s + o.trips, 0);
    $("route-summary").textContent =
      `${totalTrips} trips dispatched · ${departures.reduce((s, o) => s + o.bags, 0)} bags ordered today · ${activeOrders().length} shipment routes shown${run().unlogged_receipts ? " · older log: some opening receipts have no route" : ""}`;
    const summaries = Object.entries(data.runs).sort(
      (a, b) => a[1].summary.total_cost - b[1].summary.total_cost,
    );
    const maxCost = Math.max(...summaries.map(([, r]) => r.summary.total_cost));
    $("policy-results").innerHTML = summaries
      .map(
        ([name, r]) =>
          `<button data-run="${esc(name)}" class="${state.run === name ? "selected" : ""}" aria-pressed="${state.run === name}"><span>${esc(names[name] || name)}</span><strong>${money(r.summary.total_cost)}</strong><small>${number(r.summary.service * 100, 1)}% fill ${r.summary.meets_target ? "· target met" : "· below target"}</small><div class="cost-track"><i style="width:${(r.summary.total_cost / maxCost) * 100}%;background:${r.summary.meets_target ? "var(--teal)" : "var(--rust)"}"></i></div></button>`,
      )
      .join("");
    $("policy-results")
      .querySelectorAll("button")
      .forEach((el) => (el.onclick = () => selectRun(el.dataset.run)));
    $("result-caption").textContent =
      `Target: ${number(data.config.service * 100)}% fill. Select a policy to replay its own stock and sales history.`;
    renderCharts();
    renderMap();
    if (state.scene) state.scene.update();
  }
  for (const name of Object.keys(data.runs)) $("policy").add(new Option(names[name] || name, name));
  for (const b of data.bars) $("bar").add(new Option(`${b.id + 1}. ${b.name}`, b.id));
  $("policy").value = state.run;
  $("policy").onchange = (e) => selectRun(e.target.value);
  $("bar").onchange = (e) => selectBar(e.target.value);
  $("timeline").max = data.days.length - 1;
  $("timeline").oninput = (e) => selectDay(e.target.value);
  $("previous").onclick = () => {
    stop();
    selectDay(state.index - 1);
  };
  $("next").onclick = () => {
    stop();
    selectDay(state.index + 1);
  };
  $("play").onclick = () => (state.timer ? stop() : play());
  $("speed").onchange = () => {
    if (state.timer) play();
  };
  $("view-2d").onclick = () => setView("2d");
  $("view-3d").onclick = () => setView("3d");
  $("visitors-per-bag").onchange = (e) => {
    state.visitors = Math.min(200, Math.max(1, Math.round(Number(e.target.value) || 20)));
    e.target.value = state.visitors;
    render();
  };
  $("seed").textContent = data.config.seed;
  $("season-year").textContent = data.config.start.slice(0, 4);
  let resizeFrame;
  window.addEventListener("resize", () => {
    cancelAnimationFrame(resizeFrame);
    resizeFrame = requestAnimationFrame(renderCharts);
  });
  window.iceReplay = {
    data,
    state,
    rows,
    row,
    day,
    run,
    projection,
    coast,
    activeOrders,
    selectBar,
    setView,
    render,
    number,
  };
  render();
})();
