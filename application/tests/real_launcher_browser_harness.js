"use strict";

// Opt-in integration companion to real_launcher_browser_e2e.py. No page.route,
// injected API/business-function replacement, or simulated process completion.
const fs = require("fs");
const path = require("path");
const assert = require("assert");
const config = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const { chromium } = require(config.playwright);
const evidence = { requests: [], responses: [], runs: [], pageErrors: [] };
let browser;
let page;
const origin = new URL(config.url).origin;
const output = (name) => path.join(config.output, name);

async function newPage() {
  if (page) await page.close();
  page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on("pageerror", (error) => evidence.pageErrors.push(error.message));
  page.on("request", (request) => {
    if (request.method() === "POST") evidence.requests.push({ url: new URL(request.url()).pathname, body: request.postDataJSON() });
  });
  page.on("response", async (response) => {
    if (response.request().method() === "POST") {
      evidence.responses.push({ url: new URL(response.url()).pathname, status: response.status(), body: await response.json().catch(() => null) });
    }
  });
  await page.goto(config.url);
  await page.waitForSelector("#openProcurementButton");
  await page.waitForFunction(() => document.querySelector("#homeStatusLabel").textContent === "Ready");
}

async function finishRun(response, label, expectedStatus = "complete") {
  const start = await response.json();
  assert.strictEqual(response.status(), 200, JSON.stringify(start));
  assert.strictEqual(start.started, true, JSON.stringify(start));
  const deadline = Date.now() + 360000;
  let state;
  while (Date.now() < deadline) {
    const stateResponse = await page.request.get(`${origin}/api/state`, { headers: { "X-Launcher-Token": config.token, Origin: origin } });
    assert.strictEqual(stateResponse.status(), 200);
    state = await stateResponse.json();
    if (state.runId === start.runId && !state.running) break;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  evidence.runs.push({ label, start, final: state });
  assert.strictEqual(state.runId, start.runId);
  assert.strictEqual(state.running, false, `${label}: timed out`);
  if (expectedStatus === "complete") assert.strictEqual(state.returncode, 0, `${label}: child failed: ${JSON.stringify(state)}`);
  else assert.notStrictEqual(state.returncode, 0);
  assert.strictEqual(state.status, expectedStatus, `${label}: incorrect terminal state`);
  // Let the UI's own polling publish the completed state.
  const screen = label.startsWith("audio") ? "#audioRunScreen" : label === "analysis" ? "#analysisRunScreen" : "#runProgressView";
  await page.waitForFunction(({ screen, expectedStatus }) => {
    const root = document.querySelector(screen);
    const expected = expectedStatus === "complete" ? "complete" : expectedStatus === "failed" ? "failed" : "stopped";
    return root.querySelector(".progress-label").textContent.toLowerCase().includes(expected);
  }, { screen, expectedStatus });
  assert((await page.locator(`${screen} h2`).innerText()).toLowerCase().includes(expectedStatus), `${label}: terminal title still says Running`);
  assert.strictEqual(await page.locator(`${screen} .spinner`).isVisible(), false, `${label}: terminal spinner still visible`);
  assert.strictEqual(await page.locator(`${screen} button[id^="stop"]`).isDisabled(), true, `${label}: Stop remains enabled after completion`);
  if (expectedStatus === "complete") await page.waitForFunction((screen) => {
    const bar = document.querySelector(`${screen} .progress-bar`);
    return bar.getBoundingClientRect().width >= bar.parentElement.getBoundingClientRect().width - 1;
  }, screen);
  await page.screenshot({ path: output(`${label}.png`), fullPage: true });
}

async function procurement(mode) {
  await newPage();
  await page.click("#openProcurementButton");
  await page.fill("#sourcePathInput", config.fixtures.video);
  await page.fill("#outputRootInput", output(mode));
  const scanned = page.waitForResponse((r) => r.url().endsWith("/api/scan"));
  await page.click("#scanButton");
  const scanResponse = await scanned;
  assert.strictEqual(scanResponse.status(), 200);
  const scan = await scanResponse.json();
  assert.strictEqual(scan.groups.reduce((count, group) => count + group.videos.length, 0), 1);
  await page.waitForSelector("#reviewScreen.active");
  await page.check(`input[name="mode"][value="${mode === "focus" ? "manual" : "full"}"]`);
  if (mode === "focus") {
    await page.fill("#focusGapInput", "1");
    await page.click("#toRunButton");
    await page.locator("#manualVideoList .video-title-button").first().click();
    await page.waitForSelector("#segmentDialog[open]");
    await page.waitForFunction(() => Number.isFinite(document.querySelector("#manualPlayer").duration));
    for (const [start, end] of [["0:01", "0:03"], ["0:06", "0:08"]]) {
      await page.fill("#segmentStartInput", start);
      await page.fill("#segmentEndInput", end);
      await page.click("#addSegmentButton");
    }
    assert((await page.locator("#manualCount").innerText()).includes("2"));
    await page.screenshot({ path: output("focus-selection.png"), fullPage: true });
    await page.click("#closeSegmentDialogButton");
    const response = page.waitForResponse((r) => r.url().endsWith("/api/run"));
    await page.click("#manualRunButton");
    await finishRun(await response, mode);
  } else {
    await page.screenshot({ path: output("full-review.png"), fullPage: true });
    const response = page.waitForResponse((r) => r.url().endsWith("/api/run"));
    await page.click("#toRunButton");
    await finishRun(await response, mode);
  }
}

async function audio() {
  await newPage();
  await page.click("#openProcessingButton");
  await page.click("#openAudioProcessingButton");
  await page.check('input[name="audioMode"][value="single"]');
  await page.fill("#audioSourcePathInput", config.fixtures.video);
  await page.fill("#audioOutputRootInput", output("audio"));
  await page.uncheck("#audioEmotionsToggle");
  await page.locator("#audioInputScreen details.advanced-options summary").click();
  await page.fill("#audioWindowSecondsInput", "4");
  await page.fill("#audioStrideSecondsInput", "4");
  await page.selectOption("#audioDeviceSelect", "cpu");
  await page.screenshot({ path: output("audio-options.png"), fullPage: true });
  const response = page.waitForResponse((r) => r.url().endsWith("/api/run-audio"));
  await page.click("#runAudioButton");
  await finishRun(await response, "audio");
  // Real decoder failure: backend accepts an existing MP4 path, then FFmpeg
  // rejects its deliberately invalid bytes in the actual audio subprocess.
  await page.click("#backToAudioInputButton");
  await page.fill("#audioSourcePathInput", config.fixtures.corruptVideo);
  await page.fill("#audioOutputRootInput", output("audio-failure"));
  const failedResponse = page.waitForResponse((r) => r.url().endsWith("/api/run-audio"));
  await page.click("#runAudioButton");
  await finishRun(await failedResponse, "audio-failure", "failed");
  // Starting again after failure must reset the terminal presentation. Stop
  // the new child through the ordinary UI while it is genuinely active.
  await page.click("#backToAudioInputButton");
  await page.fill("#audioSourcePathInput", config.fixtures.video);
  await page.fill("#audioOutputRootInput", output("audio-cancel"));
  const stoppedResponse = page.waitForResponse((r) => r.url().endsWith("/api/run-audio"));
  await page.click("#runAudioButton");
  const stoppingRun = await stoppedResponse;
  await page.waitForSelector("#audioRunScreen.active");
  assert((await page.locator("#audioRunScreen h2").innerText()).startsWith("Running"));
  assert.strictEqual(await page.locator("#audioRunScreen .spinner").isVisible(), true);
  assert.strictEqual(await page.locator("#stopAudioButton").isEnabled(), true);
  const stopped = page.waitForResponse((r) => r.url().endsWith("/api/stop"));
  await page.click("#stopAudioButton");
  assert.strictEqual((await (await stopped).json()).stopping, true);
  await finishRun(stoppingRun, "audio-cancel", "stopped");
}

async function analysis() {
  await newPage();
  await page.click("#openAnalysisButton");
  await page.check("#analysisAudioEnabled");
  await page.check("#analysisAudioImportMethod");
  await page.fill("#analysisAudioSourcePath", config.fixtures.reports);
  await page.fill("#analysisOutputRootInput", output("analysis"));
  await page.click("#openAnalysisCustomizeButton");
  await page.fill("#analysisSourceManifestInput", config.fixtures.manifest);
  await page.click("#discoverAnalysisSpeakersButton");
  await page.waitForFunction(() => document.querySelector("#analysisSpeakerDiscoveryStatus").textContent.includes("4 sources"));
  await page.getByRole("checkbox", { name: "Country", exact: true }).check();
  await page.selectOption("#analysisAutomaticGroupField", "Country");
  await page.screenshot({ path: output("analysis-country-groups.png"), fullPage: true });
  await page.click("#saveAnalysisCustomizationButton");
  await page.waitForFunction(() => !document.querySelector("#runAnalysisButton").disabled);
  const response = page.waitForResponse((r) => r.url().endsWith("/api/run-analysis-workflow"));
  await page.click("#runAnalysisButton");
  await finishRun(await response, "analysis");
  const request = evidence.requests.find((r) => r.url === "/api/run-analysis-workflow");
  assert.strictEqual(request.body.analysisProfile.automatic_group_field, "Country");
}

(async () => {
  try {
    browser = await chromium.launch({ executablePath: config.browser, headless: true });
    await procurement("full");
    await procurement("focus");
    await audio();
    await analysis();
    assert.deepStrictEqual(evidence.pageErrors, []);
    assert(evidence.responses.every((r) => r.status === 200), "An actual API request failed");
    evidence.status = "passed";
  } catch (error) {
    evidence.status = "failed";
    evidence.error = error.stack;
    if (page) await page.screenshot({ path: output("failure.png"), fullPage: true }).catch(() => {});
    console.error(error.stack);
    process.exitCode = 1;
  } finally {
    fs.writeFileSync(output("browser-evidence.json"), JSON.stringify(evidence, null, 2));
    if (browser) await browser.close();
  }
})();
