import assert from "node:assert/strict";
import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

const chromeCandidates = process.platform === "win32"
  ? [
      process.env.CHROME_PATH,
      "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
      "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
      "C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe",
    ]
  : [process.env.CHROME_PATH, "google-chrome", "chromium", "chromium-browser"];

function findChrome() {
  for (const candidate of chromeCandidates.filter(Boolean)) {
    if (path.isAbsolute(candidate)) {
      const result = spawnSync(candidate, ["--version"], { encoding: "utf8" });
      if (!result.error) return candidate;
      continue;
    }
    try {
      const lookup = process.platform === "win32" ? "where.exe" : "which";
      return execFileSync(lookup, [candidate], { encoding: "utf8" }).trim().split(/\r?\n/)[0];
    } catch {
      // Try the next browser candidate.
    }
  }
  return null;
}

function measureLayout(width, height) {
  const chrome = findChrome();
  if (!chrome) return null;

  const css = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
  const fixtureDir = mkdtempSync(path.join(tmpdir(), "f4-layout-"));
  const fixturePath = path.join(fixtureDir, "index.html");
  const repeatedSections = Array.from({ length: 18 }, (_, index) =>
    `<section class="f4-section">Agent reflection ${index + 1}</section>`
  ).join("");

  writeFileSync(fixturePath, `<!doctype html>
    <html><head><meta charset="utf-8"><style>${css}</style></head>
    <body>
      <main class="tracking-page">
        <header class="tracking-page-header"><h1>Tracking</h1></header>
        <div class="tracking-grid">
          <section class="tracking-map"><div class="goong-route-map"></div></section>
          <div class="monitor-stack">
            <section class="monitor-card">F3 controls</section>
            <section class="f4-panel">${repeatedSections}</section>
          </div>
        </div>
      </main>
      <pre id="result"></pre>
      <script>
        const map = document.querySelector('.goong-route-map');
        const sidebar = document.querySelector('.monitor-stack');
        const style = getComputedStyle(sidebar);
        document.querySelector('#result').textContent = JSON.stringify({
          mapHeight: map.getBoundingClientRect().height,
          sidebarHeight: sidebar.getBoundingClientRect().height,
          sidebarClientHeight: sidebar.clientHeight,
          sidebarScrollHeight: sidebar.scrollHeight,
          overflowY: style.overflowY,
          position: style.position,
        });
      </script>
    </body></html>`, "utf8");

  try {
    const output = execFileSync(chrome, [
      "--headless=new",
      "--no-sandbox",
      "--disable-gpu",
      "--disable-background-networking",
      "--allow-file-access-from-files",
      "--log-level=3",
      `--window-size=${width},${height}`,
      "--dump-dom",
      pathToFileURL(fixturePath).href,
    ], {
      encoding: "utf8",
      maxBuffer: 10 * 1024 * 1024,
      stdio: ["ignore", "pipe", "ignore"],
    });
    const match = output.match(/<pre id="result">([^<]+)<\/pre>/);
    assert.ok(match, "Chrome should return the computed layout metrics");
    return JSON.parse(match[1].replaceAll("&quot;", '"'));
  } finally {
    rmSync(fixtureDir, { recursive: true, force: true });
  }
}

test("desktop tracking keeps the right sidebar aligned with the map and scrolls reflection internally", (t) => {
  const metrics = measureLayout(1440, 900);
  if (!metrics) {
    t.skip("Chrome or Edge is required for the layout regression test");
    return;
  }

  assert.equal(metrics.overflowY, "auto");
  assert.ok(Math.abs(metrics.sidebarHeight - metrics.mapHeight) <= 1);
  assert.ok(metrics.sidebarScrollHeight > metrics.sidebarClientHeight);
});

test("narrow tracking uses natural page scrolling instead of a nested sidebar", (t) => {
  const metrics = measureLayout(800, 900);
  if (!metrics) {
    t.skip("Chrome or Edge is required for the layout regression test");
    return;
  }

  assert.equal(metrics.position, "static");
  assert.equal(metrics.overflowY, "visible");
  assert.equal(metrics.sidebarScrollHeight, metrics.sidebarClientHeight);
});
