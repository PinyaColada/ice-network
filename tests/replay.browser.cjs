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
    await page.setViewportSize({ width: 390, height: 844 });
    await page.click("#view-3d");
    await page.locator("#reset-camera").click();
    await page.waitForTimeout(300);
    assert(await page.evaluate(() => document.body.scrollWidth <= innerWidth));
    await page.screenshot({ path: path.join(output, "replay-mobile.png"), fullPage: true });
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);

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
