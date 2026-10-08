/* Optional browser integration check. Requires Playwright; it is not a runtime dependency. */
const assert = require("node:assert/strict");
const path = require("node:path");
const { pathToFileURL } = require("node:url");
const { chromium } = require("playwright");

(async () => {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.ICE_CHROMIUM_PATH ? { executablePath: process.env.ICE_CHROMIUM_PATH } : {}),
    args: ["--no-sandbox", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
  });
  try {
    const assertMapVisible = async (target) => {
      const layout = await target.evaluate(() => {
        const map = document.querySelector("#map"),
          stage = document.querySelector("#stage");
        const canvas = stage.querySelector("canvas");
        const m = map.getBoundingClientRect(),
          s = stage.getBoundingClientRect();
        return {
          hiddenCanvas: !canvas || getComputedStyle(canvas).display === "none",
          inside:
            m.width > 0 &&
            m.height > 0 &&
            m.top >= s.top - 1 &&
            m.left >= s.left - 1 &&
            m.bottom <= s.bottom + 1 &&
            m.right <= s.right + 1,
          bars: map.querySelectorAll("[data-bar]").length,
          scroll: stage.scrollTop,
        };
      });
      assert(layout.hiddenCanvas, "3D canvas must not occupy space in 2D mode");
      assert(layout.inside, "SVG map must be inside its clipped stage before any auto-scrolling");
      assert.equal(layout.bars, 12);
      assert.equal(layout.scroll, 0);
    };
    const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
    const errors = [],
      external = [];
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      if (/^https?:/.test(request.url())) external.push(request.url());
    });
    const output = path.resolve(__dirname, "../artifacts");
    await page.goto(pathToFileURL(path.join(output, "replay.html")).href);
    await page.waitForFunction(() => window.iceReplay?.state.scene);
    await page.waitForFunction(() =>
      iceReplay.state.scene.inspectVehicles().some((v) => v.returning),
    );
    const firstFleet = await page.evaluate(() => iceReplay.state.scene.inspectVehicles());
    assert(firstFleet.some((v) => !v.returning && v.color === "2d817d"));
    assert(firstFleet.some((v) => v.returning && v.color === "8b5fb5"));
    const firstReturn = firstFleet.find((v) => v.returning);
    await page.waitForTimeout(250);
    const movingReturn = await page.evaluate(
      ({ bar, depot, arrival }) =>
        iceReplay.state.scene
          .inspectVehicles()
          .find((v) => v.bar === bar && v.depot === depot && v.arrival === arrival),
      firstReturn,
    );
    assert(movingReturn.progress < firstReturn.progress, "empty truck must move toward its depot");
    await page.waitForFunction(() =>
      iceReplay.state.scene
        .inspectVehicles()
        .filter((v) => v.returning)
        .every((v) => v.progress === 0),
    );
    const parked = await page.evaluate(() => {
      const a = iceReplay,
        v = a.state.scene.inspectVehicles().find((v) => v.returning);
      const depot = a.data.depots[v.depot],
        [x, z] = a.projection(depot.lon, depot.lat);
      return {
        position: v.position,
        depot: [x, 2, z],
        count: a.state.scene.inspectVehicles().length,
      };
    });
    assert.deepEqual(parked.position, parked.depot);
    await page.selectOption("#bar", "1");
    await page.waitForTimeout(100);
    assert.equal(
      await page.evaluate(() => iceReplay.state.scene.inspectVehicles().length),
      parked.count,
    );
    assert(
      await page.evaluate(() =>
        iceReplay.state.scene
          .inspectVehicles()
          .filter((v) => v.returning)
          .every((v) => v.progress === 0),
      ),
      "selection must not restart parked trucks",
    );
    const chooseDay = async (index) =>
      page.locator("#timeline").evaluate((el, value) => {
        el.value = value;
        el.dispatchEvent(new Event("input", { bubbles: true }));
      }, index);

    await page.selectOption("#policy", "optimizer/hurdle");
    await page.selectOption("#bar", "7");
    await chooseDay(25);
    const expected = await page.evaluate(() => {
      const a = iceReplay;
      return {
        stock: a.number(a.rows().reduce((s, r) => s + r.closing, 0)),
        selected: a.row().bar,
        day: a.day(),
        frozen: JSON.stringify(a.run().summary),
        demand: a.row().latent_demand,
      };
    });
    assert.equal(await page.locator("#stock-kpi").innerText(), expected.stock);
    assert.equal(expected.selected, 7);
    await page.fill("#visitors-per-bag", "30");
    await page.locator("#visitors-per-bag").dispatchEvent("change");
    assert(
      (await page.locator("#customer-readout").innerText()).includes(
        (expected.demand * 30).toLocaleString("en-GB"),
      ),
    );
    assert.equal(
      await page.evaluate(() => JSON.stringify(iceReplay.run().summary)),
      expected.frozen,
    );

    await page.selectOption("#policy", "naive/none");
    assert.match(await page.locator("#forecast-status").innerText(), /no forecast/);
    assert.equal(await page.locator("#forecast-chart polygon").count(), 0);
    await page.click("#view-2d");
    await assertMapVisible(page);
    assert(await page.locator("#analytics").isVisible());
    const metrics = await page.evaluate(() => {
      const a = iceReplay,
        departures = a.run().orders.filter((o) => o.departure === a.day());
      const trips = departures.reduce((s, o) => s + o.trips, 0);
      const bags = departures.reduce((s, o) => s + o.bags, 0);
      const palma = departures.filter((o) => o.depot === 0).reduce((s, o) => s + o.bags, 0);
      const sales = a.rows().reduce((s, r) => s + r.sales, 0);
      const demand = a.rows().reduce((s, r) => s + r.latent_demand, 0);
      return {
        palma: a.number(palma),
        unused: a.number(a.data.depots[0].production - palma),
        fill: demand ? a.number((sales / demand) * 100, 1) + "%" : "—",
        load: trips
          ? a.number((bags / (trips * a.data.config.truck_capacity)) * 100, 1) + "%"
          : "—",
      };
    });
    assert.equal(await page.locator("#depot-0-stats strong").nth(0).innerText(), metrics.palma);
    assert.equal(await page.locator("#depot-0-stats strong").nth(2).innerText(), metrics.unused);
    assert.equal(await page.locator("#eff-fill").innerText(), metrics.fill);
    assert.equal(await page.locator("#eff-load").innerText(), metrics.load);
    assert((await page.locator('#efficiency-chart [data-series="truck-load"]').count()) > 0);
    await page.locator('#map [data-bar="10"]').click();
    assert.equal(await page.locator("#bar").inputValue(), "10");
    await page.locator("#forecast-chart .hit-zone").click({ position: { x: 50, y: 50 } });
    assert.notEqual(await page.evaluate(() => iceReplay.state.index), 25);

    await chooseDay(0);
    await page.selectOption("#speed", "180");
    await page.click("#play");
    await page.waitForFunction(() => iceReplay.state.index >= 2);
    await page.click("#play");
    const paused = await page.evaluate(() => iceReplay.state.index);
    await page.waitForTimeout(300);
    assert.equal(await page.evaluate(() => iceReplay.state.index), paused);
    const last = await page.evaluate(() => iceReplay.data.days.length - 1);
    await chooseDay(last - 1);
    await page.click("#play");
    await page.waitForFunction(() => iceReplay.state.timer === null);
    assert.equal(await page.evaluate(() => iceReplay.state.index), last);
    assert.equal(await page.locator("#eff-load").innerText(), "—");
    assert(
      (await page.locator('#efficiency-chart [data-series="truck-load"]').count()) > 0,
      "a no-departure day must not erase the rest of the truck-load history",
    );

    await page.selectOption("#policy", "quantile/seasonal");
    await page.selectOption("#bar", "0");
    await chooseDay(40);
    await page.fill("#visitors-per-bag", "20");
    await page.locator("#visitors-per-bag").dispatchEvent("change");
    await page.click("#view-3d");
    await page.locator("#reset-camera").click();
    await page.evaluate(() => iceReplay.state.scene.controls.update());
    await page.waitForTimeout(500);
    await page.screenshot({ path: path.join(output, "replay-3d.png"), fullPage: true });
    const canvas = await page.locator("#stage canvas").boundingBox();
    const before = await page.evaluate(() => iceReplay.state.scene.camera.position.toArray());
    await page.mouse.move(canvas.x + 150, canvas.y + 100);
    await page.mouse.down();
    await page.mouse.move(canvas.x + 220, canvas.y + 130, { steps: 8 });
    await page.mouse.up();
    await page.waitForTimeout(300);
    assert.notDeepEqual(
      await page.evaluate(() => iceReplay.state.scene.camera.position.toArray()),
      before,
    );

    await page.click("#view-2d");
    await page.screenshot({ path: path.join(output, "replay-2d.png"), fullPage: true });
    await assertMapVisible(page);
    await page.locator("#analytics").screenshot({ path: path.join(output, "efficiency.png") });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.click("#view-3d");
    await page.locator("#reset-camera").click();
    await page.waitForTimeout(300);
    assert(await page.evaluate(() => document.body.scrollWidth <= innerWidth));
    await page.screenshot({ path: path.join(output, "replay-mobile.png"), fullPage: true });
    await page.click("#view-2d");
    await assertMapVisible(page);
    await page.waitForFunction(
      () => document.querySelector("#cost-chart svg").viewBox.baseVal.width < 390,
    );
    assert(await page.evaluate(() => document.body.scrollWidth <= innerWidth));
    await page
      .locator("#analytics")
      .screenshot({ path: path.join(output, "efficiency-mobile.png") });
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);

    const direct = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
    direct.on("pageerror", (error) => errors.push(error.message));
    await direct.goto(pathToFileURL(path.join(output, "replay.html")).href + "#2d");
    await direct.waitForFunction(() => iceReplay.state.scene);
    await assertMapVisible(direct);
    await direct.locator(".island").screenshot({ path: path.join(output, "map-fixed.png") });
    await direct.reload();
    await direct.waitForFunction(() => iceReplay.state.scene);
    await assertMapVisible(direct);
    await direct.selectOption("#policy", "optimizer/hurdle");
    await assertMapVisible(direct);
    await direct.close();
    assert.deepEqual(errors, []);

    const fallback = await browser.newPage();
    await fallback.addInitScript(() => {
      const original = HTMLCanvasElement.prototype.getContext;
      HTMLCanvasElement.prototype.getContext = function (kind, ...args) {
        return kind.startsWith("webgl") ? null : original.call(this, kind, ...args);
      };
    });
    await fallback.goto(pathToFileURL(path.join(output, "replay.html")).href);
    await fallback.waitForFunction(() => iceReplay.state.view === "2d");
    assert(await fallback.locator("#webgl-fallback").isVisible());
    assert(await fallback.locator("#view-3d").isDisabled());
    await assertMapVisible(fallback);
    console.log(
      "Replay QA passed: data, controls, playback, 2D/3D, mobile, offline, WebGL fallback.",
    );
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
