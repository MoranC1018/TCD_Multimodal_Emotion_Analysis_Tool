"use strict";

const assert = require("assert");
const fs = require("fs");
const http = require("http");
const path = require("path");

const [uiRoot, playwrightRoot, browserConfigJson, screenshotDir] = process.argv.slice(1);
if (![uiRoot, playwrightRoot, browserConfigJson, screenshotDir].every(Boolean)) {
  throw new Error("Pass UI root, Playwright root, browser configuration, and screenshot directory.");
}
let chromium;
try {
  ({ chromium } = require(playwrightRoot));
} catch (error) {
  console.error(`Playwright could not be loaded from ${playwrightRoot}: ${error.message}`);
  process.exit(77);
}
const browserConfig = JSON.parse(browserConfigJson);

class BrowserAutomationUnavailable extends Error {
  constructor(message) {
    super(message);
    this.name = "BrowserAutomationUnavailable";
  }
}

async function launchBrowser() {
  const attempts = [];
  if (browserConfig.explicitExecutable) {
    attempts.push({ executablePath: browserConfig.executablePath });
  } else {
    attempts.push({ channel: browserConfig.channel || "msedge" });
    if (browserConfig.executablePath) {
      attempts.push({ executablePath: browserConfig.executablePath });
    }
  }

  const failures = [];
  for (const options of attempts) {
    try {
      return await chromium.launch({ ...options, headless: true });
    } catch (error) {
      failures.push(`${JSON.stringify(options)}: ${error.message}`);
    }
  }
  throw new BrowserAutomationUnavailable(
    `Microsoft Edge could not be launched. Attempts:\n${failures.join("\n")}`,
  );
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((accept, decline) => {
    resolve = accept;
    reject = decline;
  });
  return { promise, resolve, reject };
}

function responseJson(route, payload, status = 200) {
  return route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(payload),
  });
}

function statePayload(backend) {
  return {
    access: { termsAccepted: true, eulaPath: "C:\\local\\eula.txt" },
    settings: { resourceCapabilities: {} },
    defaultOutputRoot: "C:\\output\\procurement",
    defaultAudioOutputRoot: "C:\\output\\audio",
    defaultAnalysisOutputRoot: "C:\\output\\analysis",
    running: backend.running,
    status: backend.status,
    runId: backend.runId,
    progress: backend.progress,
  };
}

function contentType(filePath) {
  if (filePath.endsWith(".html")) return "text/html; charset=utf-8";
  if (filePath.endsWith(".js")) return "text/javascript; charset=utf-8";
  if (filePath.endsWith(".css")) return "text/css; charset=utf-8";
  if (filePath.endsWith(".jpg") || filePath.endsWith(".jpeg")) return "image/jpeg";
  if (filePath.endsWith(".png")) return "image/png";
  if (filePath.endsWith(".ico")) return "image/x-icon";
  return "application/octet-stream";
}

async function waitFor(predicate, message, timeoutMs = 5000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await new Promise((resolve) => setTimeout(resolve, 20));
  }
  throw new Error(message);
}

function speakerPayload(prefix = "Speaker") {
  return {
    speakers: [
      { key: `${prefix.toLowerCase()}_a`, name: `${prefix} A`, availableIn: ["imotions"] },
      { key: `${prefix.toLowerCase()}_b`, name: `${prefix} B`, availableIn: ["imotions"] },
    ],
    warnings: [],
  };
}

function profileContextPayload(prefix = "Researcher") {
  return {
    sourceManifest: "C:\\run\\source_manifest.json",
    sourceManifestSha256: "a".repeat(64),
    metadataFields: [
      { name: "Country", values: ["Ireland", "Japan"] },
      { name: "Wave", values: ["First", "Second"] },
    ],
    speakers: [
      { id: `${prefix.toLowerCase()}_a`, name: `${prefix} A`, sourceIds: ["source-0001"] },
      { id: `${prefix.toLowerCase()}_b`, name: `${prefix} B`, sourceIds: ["source-0002"] },
    ],
    sources: [
      { id: "source-0001", title: `${prefix} interview A`, speakerId: `${prefix.toLowerCase()}_a`, speaker: `${prefix} A`, metadata: { Country: "Ireland", Wave: "First" } },
      { id: "source-0002", title: `${prefix} interview B`, speakerId: `${prefix.toLowerCase()}_b`, speaker: `${prefix} B`, metadata: { Country: "Japan", Wave: "Second" } },
    ],
  };
}

function sharedSpeakerProfileContext() {
  const payload = profileContextPayload("Researcher");
  payload.speakers = [
    { id: "researcher_a", name: "Researcher A", sourceIds: ["source-0001", "source-0002"] },
  ];
  payload.sources[1] = {
    ...payload.sources[1],
    speakerId: "researcher_a",
    speaker: "Researcher A",
  };
  return payload;
}

async function createTestPage(browser, origin, viewport) {
  const page = await browser.newPage({ viewport });
  const backend = {
    running: false,
    status: "idle",
    runId: 0,
    progress: {},
    nextRunId: 70,
    discoveries: [],
    autoDiscoveryPayload: null,
    autoProfileContext: null,
    profileContextBodies: [],
    requireSourceManifest: false,
    runBodies: [],
    holdStateOnNextRun: false,
    stateGate: null,
    stateWaitCount: 0,
  };

  await page.route(`${origin}/api/**`, async (route) => {
    const request = route.request();
    const pathname = new URL(request.url()).pathname;
    if (pathname === "/api/state") {
      if (backend.stateGate) {
        backend.stateWaitCount += 1;
        await backend.stateGate.promise;
      }
      return responseJson(route, statePayload(backend));
    }
    if (pathname === "/api/validate-path") {
      const body = request.postDataJSON();
      return responseJson(route, { valid: true, path: body.path });
    }
    if (pathname === "/api/analysis-speakers") {
      if (backend.autoDiscoveryPayload) {
        return responseJson(route, backend.autoDiscoveryPayload);
      }
      const pending = deferred();
      backend.discoveries.push(pending);
      const payload = await pending.promise;
      return responseJson(route, payload);
    }
    if (pathname === "/api/analysis-profile-context") {
      const body = request.postDataJSON();
      backend.profileContextBodies.push(body);
      if (backend.requireSourceManifest && !body.sourceManifest) {
        return responseJson(route, { error: "Choose a procurement source manifest for sidecarless results." }, 400);
      }
      if (backend.autoProfileContext) {
        return responseJson(route, backend.autoProfileContext);
      }
      const pending = deferred();
      backend.discoveries.push(pending);
      const payload = await pending.promise;
      return responseJson(route, payload);
    }
    if (pathname === "/api/run-analysis-workflow") {
      backend.runBodies.push(request.postDataJSON());
      backend.running = true;
      backend.status = "running";
      backend.runId = ++backend.nextRunId;
      backend.progress = { mode: "analysis-workflow", label: "Running" };
      if (backend.holdStateOnNextRun) {
        backend.holdStateOnNextRun = false;
        backend.stateGate = deferred();
      }
      return responseJson(route, { runId: backend.runId });
    }
    if (pathname === "/api/stop") {
      backend.running = false;
      backend.status = "stopped";
      return responseJson(route, { stopped: true });
    }
    return responseJson(route, {});
  });

  await page.goto(origin, { waitUntil: "domcontentloaded" });
  await page.click("#openAnalysisButton");
  await page.waitForSelector("#analysisInputScreen.active");
  return { page, backend };
}

async function staleDiscoveryAndGroupAccessibility(browser, origin) {
  const { page, backend } = await createTestPage(browser, origin, { width: 1280, height: 1000 });
  try {
    await page.fill("#analysisImotionsSourcePath", "C:\\source-a");
    await page.click("#openAnalysisCustomizeButton");
    await waitFor(() => backend.discoveries.length === 1, "First discovery did not start.");

    await page.click("#backFromAnalysisCustomizeButton");
    await page.fill("#analysisImotionsSourcePath", "C:\\source-b");
    await page.click("#openAnalysisCustomizeButton");
    await waitFor(() => backend.discoveries.length === 2, "Second discovery did not start.");
    backend.discoveries[1].resolve(profileContextPayload("Researcher"));
    await page.waitForFunction(() => document.querySelector("#analysisSpeakerDiscoveryStatus").textContent.includes("2 sources"));
    backend.discoveries[0].resolve(profileContextPayload("Stale"));
    await page.waitForTimeout(50);
    assert.ok((await page.locator("#analysisSpeakerDiscoveryStatus").textContent()).includes("2 sources"));

    const liveStatus = page.locator("#analysisGroupWarningStatus");
    await liveStatus.evaluate((element) => { element.dataset.stabilityProbe = "stable"; });
    await page.click("#addAnalysisSpeakerGroupButton");
    assert.strictEqual(await page.evaluate(() => document.activeElement.value), "Manual group 1");
    await page.getByLabel("Assign Researcher A to Manual group 1").check();
    await page.click("#addAnalysisSpeakerGroupButton");
    assert.strictEqual(await page.evaluate(() => document.activeElement.value), "Manual group 2");
    assert.strictEqual(await page.getByLabel("Assign Researcher interview A, Researcher A to Manual group 2").isDisabled(), true);
    assert.strictEqual(await liveStatus.getAttribute("data-stability-probe"), "stable");

    await page.getByLabel("Assign Researcher interview B, Researcher B to Manual group 2").check();
    const groupNames = page.getByLabel("Manual group name");
    await groupNames.nth(1).fill("Renamed group");
    assert.strictEqual(await page.getByRole("button", { name: "Remove Renamed group" }).count(), 1);
    assert.strictEqual(await page.getByLabel("Assign Researcher interview B, Researcher B to Renamed group").count(), 1);

    await page.getByRole("button", { name: "Remove Manual group 1" }).click();
    assert.strictEqual(await page.evaluate(() => document.activeElement.value), "Renamed group");
    await page.getByRole("button", { name: "Remove Renamed group" }).click();
    assert.strictEqual(await page.evaluate(() => document.activeElement.id), "addAnalysisSpeakerGroupButton");
  } finally {
    await page.close();
  }
}

async function submissionLockAndPayloads(browser, origin) {
  const { page, backend } = await createTestPage(browser, origin, { width: 1280, height: 1000 });
  try {
    await page.fill("#analysisImotionsSourcePath", "C:\\imported-reports");
    await page.check("#analysisImotionsImportMethod");
    assert.strictEqual(await page.locator("#analysisGraphsOption").isHidden(), true);
    assert.strictEqual(await page.locator("#analysisLogscaleOption").isHidden(), true);
    await page.uncheck("#analysisWriteCombinedToggle");
    assert.strictEqual(await page.locator("#analysisDefaultReferenceInput").isDisabled(), true);
    assert.strictEqual(await page.locator("#runAnalysisButton").isEnabled(), true);

    backend.holdStateOnNextRun = true;
    await page.click("#runAnalysisButton");
    await waitFor(() => backend.runBodies.length === 1, "Analysis start request was not sent.");
    await waitFor(() => backend.stateWaitCount > 0, "Run-screen state transition was not held.");
    assert.strictEqual(await page.locator("#analysisInputScreen").getAttribute("class"), "screen active");
    assert.strictEqual(await page.locator("#runAnalysisButton").isDisabled(), true);
    assert.strictEqual(await page.locator("#analysisImotionsSourcePath").isDisabled(), true);
    await page.evaluate(() => document.querySelector("#runAnalysisButton").click());
    await page.waitForTimeout(75);
    assert.strictEqual(backend.runBodies.length, 1, "A repeated click submitted a competing run.");

    const importPayload = backend.runBodies[0];
    assert.strictEqual(importPayload.writeCombinedWorkbook, false);
    assert.deepStrictEqual(importPayload.speakerGroups, []);
    assert.strictEqual(importPayload.analysisProfile, null);
    assert.deepStrictEqual(importPayload.referenceOverrides, {});
    assert.strictEqual(importPayload.defaultReference, 0);
    assert.strictEqual(importPayload.writeGraphs, false);
    assert.strictEqual(importPayload.includeLogscale, false);

    backend.stateGate.resolve();
    backend.stateGate = null;
    await page.waitForSelector("#analysisRunScreen.active");
    await page.click("#backToAnalysisInputButton");
    await page.waitForSelector("#analysisInputScreen.active");
    assert.strictEqual(await page.locator("#runAnalysisButton").isDisabled(), true);
    assert.strictEqual(await page.locator("#analysisImotionsSourcePath").isDisabled(), true);

    backend.running = false;
    backend.status = "complete";
    backend.progress = { mode: "analysis-workflow", label: "Complete" };
    await page.evaluate(() => pollState());
    await page.waitForFunction(() => !document.querySelector("#analysisImotionsSourcePath").disabled);
    assert.strictEqual(await page.locator("#runAnalysisButton").isEnabled(), true);

    await page.check("#analysisImotionsRunMethod");
    await page.check("#analysisWriteCombinedToggle");
    backend.autoProfileContext = profileContextPayload("Researcher");
    await page.click("#openAnalysisCustomizeButton");
    await page.waitForSelector("#analysisCustomizeScreen.active");
    await page.waitForFunction(() => document.querySelector("#analysisSpeakerDiscoveryStatus").textContent.includes("2 sources"));
    await page.getByRole("checkbox", { name: "Country", exact: true }).check();
    await page.selectOption("#analysisAutomaticGroupField", "Country");
    await page.click("#saveAnalysisCustomizationButton");
    await page.waitForSelector("#analysisInputScreen.active");
    await page.locator("#analysisStatisticalAdvanced").evaluate((details) => { details.open = true; });
    await page.fill("#analysisDefaultReferenceInput", "1.5");
    await page.fill("#analysisReferenceOverridesInput", '{"Video|Anger": 2}');
    await page.check("#analysisLogscaleToggle");
    await page.click("#runAnalysisButton");
    await waitFor(() => backend.runBodies.length === 2, "Combined Analysis request was not sent.");
    const combinedPayload = backend.runBodies[1];
    assert.strictEqual(combinedPayload.writeCombinedWorkbook, true);
    assert.deepStrictEqual(combinedPayload.speakerGroups, []);
    assert.deepStrictEqual(combinedPayload.analysisProfile.sort_fields, ["Country"]);
    assert.strictEqual(combinedPayload.analysisProfile.automatic_group_field, "Country");
    assert.strictEqual(combinedPayload.defaultReference, 1.5);
    assert.deepStrictEqual(combinedPayload.referenceOverrides, { "Video|Anger": 2 });
    assert.strictEqual(combinedPayload.includeConstructComparison, true);
    assert.strictEqual(combinedPayload.includeProbabilitySheets, true);
    assert.strictEqual(combinedPayload.confidenceLevel, 0.95);
    assert.strictEqual(combinedPayload.headlinePolicy, "weighted");
    assert.strictEqual(combinedPayload.writeGraphs, true);
    assert.strictEqual(combinedPayload.includeLogscale, true);
  } finally {
    await page.close();
  }
}

async function responsiveSmoke(browser, origin) {
  const { page, backend } = await createTestPage(browser, origin, { width: 1440, height: 1000 });
  try {
    const desktopBoxes = await page.locator(".analysis-modality-card").evaluateAll((cards) =>
      cards.map((card) => card.getBoundingClientRect().toJSON()),
    );
    assert.ok(desktopBoxes.every((box) => Math.abs(box.y - desktopBoxes[0].y) < 2));
    backend.autoProfileContext = profileContextPayload("Researcher");
    await page.fill("#analysisImotionsSourcePath", "C:\\source");
    await page.click("#openAnalysisCustomizeButton");
    await page.waitForSelector("#analysisCustomizeScreen.active");
    await page.waitForFunction(() => document.querySelector("#analysisSpeakerDiscoveryStatus").textContent.includes("2 sources"));
    assert.strictEqual(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    const desktopPath = path.join(screenshotDir, "analysis-customize-desktop.png");
    await page.screenshot({ path: desktopPath, fullPage: true });
    assert.ok(fs.statSync(desktopPath).size > 10000);

    await page.setViewportSize({ width: 700, height: 1200 });
    const narrowBoxes = await page.locator(".analysis-customize-layout > .input-panel").evaluateAll((panels) =>
      panels.slice(0, 3).map((panel) => panel.getBoundingClientRect().toJSON()),
    );
    assert.ok(narrowBoxes[1].y > narrowBoxes[0].y && narrowBoxes[2].y > narrowBoxes[1].y);
    assert.strictEqual(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    const narrowPath = path.join(screenshotDir, "analysis-customize-narrow.png");
    await page.screenshot({ path: narrowPath, fullPage: true });
    assert.ok(fs.statSync(narrowPath).size > 10000);
  } finally {
    await page.close();
  }
}

async function homeBrandingResponsive(browser, origin) {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  try {
    await page.goto(origin, { waitUntil: "domcontentloaded" });
    const logo = page.locator(".trinity-main-logo");
    await logo.waitFor({ state: "visible" });
    await page.waitForFunction(() => {
      const image = document.querySelector(".trinity-main-logo");
      return image instanceof HTMLImageElement && image.complete && image.naturalWidth > 0;
    });
    const desktop = await logo.evaluate((image) => {
      const rect = image.getBoundingClientRect();
      return {
        naturalWidth: image.naturalWidth,
        naturalHeight: image.naturalHeight,
        width: rect.width,
        height: rect.height,
        right: rect.right,
      };
    });
    assert.deepStrictEqual(
      [desktop.naturalWidth, desktop.naturalHeight],
      [1713, 591],
      "The home screen must render the complete official horizontal Trinity logo.",
    );
    assert.ok(desktop.width >= 500);
    assert.ok(Math.abs(desktop.width / desktop.height - 1713 / 591) < 0.02);
    assert.ok(desktop.right <= 1440);
    assert.strictEqual(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);

    await page.setViewportSize({ width: 390, height: 844 });
    const narrow = await logo.evaluate((image) => {
      const rect = image.getBoundingClientRect();
      return { width: rect.width, height: rect.height, left: rect.left, right: rect.right };
    });
    assert.ok(narrow.width >= 300);
    assert.ok(Math.abs(narrow.width / narrow.height - 1713 / 591) < 0.02);
    assert.ok(narrow.left >= 0 && narrow.right <= 390);
    assert.strictEqual(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
  } finally {
    await page.close();
  }
}

async function invalidSourceErrorStaysContained(browser, origin) {
  const invalidSource = "https://www.youtube.com/watch?v=";
  const scanError = "Folder does not exist: C:\\ResearchWorkspace\\MultimodalEmotionAnalysisTool\\ProcurementRuns\\CandidateOne\\https:\\www.youtube.com\\watch?v=";

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 390, height: 844 },
  ]) {
    const page = await browser.newPage({ viewport });
    try {
      const backend = { running: false, status: "idle", runId: 0, progress: {} };
      await page.route(`${origin}/api/**`, async (route) => {
        const pathname = new URL(route.request().url()).pathname;
        if (pathname === "/api/state") {
          return responseJson(route, statePayload(backend));
        }
        if (pathname === "/api/scan") {
          return responseJson(route, { error: scanError }, 400);
        }
        return responseJson(route, {});
      });

      await page.goto(origin, { waitUntil: "domcontentloaded" });
      await page.click("#openProcurementButton");
      await page.fill("#sourcePathInput", invalidSource);
      await page.click("#scanButton");
      await page.waitForFunction(
        (expected) => document.querySelector("#statusLabel")?.textContent === expected,
        scanError,
      );

      const geometry = await page.evaluate(() => {
        const bounds = (selector) => {
          const element = document.querySelector(selector);
          const rect = element.getBoundingClientRect();
          return {
            clientWidth: element.clientWidth,
            scrollWidth: element.scrollWidth,
            left: rect.left,
            right: rect.right,
          };
        };
        return {
          viewportWidth: window.innerWidth,
          documentWidth: document.documentElement.scrollWidth,
          status: bounds("#statusLabel"),
          rail: bounds(".step-rail"),
          inputPanel: bounds("#inputScreen .input-panel"),
        };
      });

      assert.ok(
        geometry.status.right <= geometry.rail.right,
        `The status escaped the step rail at ${viewport.width}px.`,
      );
      assert.ok(
        geometry.status.scrollWidth <= geometry.status.clientWidth,
        `The status text overflowed its own box at ${viewport.width}px.`,
      );
      assert.ok(
        geometry.rail.scrollWidth <= geometry.rail.clientWidth,
        `The step rail overflowed at ${viewport.width}px.`,
      );
      assert.ok(
        geometry.documentWidth <= geometry.viewportWidth,
        `The document widened beyond the ${viewport.width}px viewport.`,
      );
      assert.ok(
        geometry.inputPanel.left >= 0 && geometry.inputPanel.right <= geometry.viewportWidth,
        `The input panel escaped the ${viewport.width}px viewport.`,
      );
    } finally {
      await page.close();
    }
  }
}

async function textGroupingPreflight(browser, origin) {
  const { page, backend } = await createTestPage(browser, origin, { width: 1280, height: 1000 });
  try {
    await page.fill("#analysisImotionsSourcePath", "C:\\video-reports");
    await page.check("#analysisTextEnabled");
    await page.fill("#analysisTextSourcePath", "C:\\text-results");
    backend.autoProfileContext = sharedSpeakerProfileContext();
    await page.click("#openAnalysisCustomizeButton");
    await page.waitForSelector("#analysisCustomizeScreen.active");
    await page.waitForFunction(() => document.querySelector("#analysisSpeakerDiscoveryStatus").textContent.includes("2 sources"));
    await page.selectOption("#analysisAutomaticGroupField", "Country");
    assert.strictEqual(await page.locator("#saveAnalysisCustomizationButton").isDisabled(), true);
    await page.waitForFunction(() => document.querySelector("#analysisGroupWarningStatus").textContent.includes("Text is speaker-level"));
    assert.ok((await page.locator("#analysisGroupWarningStatus").textContent()).includes("Researcher A"));
  } finally {
    await page.close();
  }
}

async function sidecarlessManifestSelection(browser, origin) {
  const { page, backend } = await createTestPage(browser, origin, { width: 1280, height: 1000 });
  try {
    backend.requireSourceManifest = true;
    backend.autoProfileContext = profileContextPayload("Legacy");
    await page.uncheck("#analysisImotionsEnabled");
    await page.check("#analysisTextEnabled");
    await page.fill("#analysisTextSourcePath", "C:\\ordinary-text-results");
    await page.click("#openAnalysisCustomizeButton");
    await page.waitForSelector("#analysisCustomizeScreen.active");
    await page.waitForFunction(() => document.querySelector("#analysisSpeakerDiscoveryStatus").textContent.includes("Choose a procurement source manifest"));
    assert.deepStrictEqual(
      backend.profileContextBodies[0].modalities.map((item) => item.name),
      ["text"],
    );
    assert.strictEqual(backend.profileContextBodies[0].sourceManifest, undefined);

    await page.fill("#analysisSourceManifestInput", "C:\\procurement-run\\source_manifest.json");
    await page.click("#discoverAnalysisSpeakersButton");
    await page.waitForFunction(() => document.querySelector("#analysisSpeakerDiscoveryStatus").textContent.includes("2 sources"));
    assert.strictEqual(
      backend.profileContextBodies.at(-1).sourceManifest,
      "C:\\procurement-run\\source_manifest.json",
    );

    await page.click("#backFromAnalysisCustomizeButton");
    await page.check("#analysisImotionsEnabled");
    await page.check("#analysisImotionsImportMethod");
    await page.fill("#analysisImotionsSourcePath", "C:\\ordinary-imotions-results");
    await page.click("#openAnalysisCustomizeButton");
    await page.waitForFunction(() => document.querySelector("#analysisSpeakerDiscoveryStatus").textContent.includes("2 sources"));
    assert.deepStrictEqual(
      backend.profileContextBodies.at(-1).modalities.map((item) => item.name).sort(),
      ["imotions", "text"],
    );
    assert.strictEqual(
      backend.profileContextBodies.at(-1).sourceManifest,
      "C:\\procurement-run\\source_manifest.json",
    );
  } finally {
    await page.close();
  }
}

async function workflowFailureDetail(browser, origin) {
  const { page, backend } = await createTestPage(browser, origin, { width: 1280, height: 1000 });
  try {
    await page.fill("#analysisImotionsSourcePath", "C:\\imported-reports");
    await page.check("#analysisImotionsImportMethod");
    await page.uncheck("#analysisWriteCombinedToggle");
    await page.click("#runAnalysisButton");
    await page.waitForSelector("#analysisRunScreen.active");

    backend.running = false;
    backend.status = "failed";
    backend.progress = {
      mode: "analysis-workflow",
      label: "Combined workbook failed: Unknown reference override: typo",
      failedStage: "combined workbook",
      error: "Combined workbook failed: Unknown reference override: typo",
      completedOutputs: { video: "C:\\reports\\video" },
    };
    await page.evaluate(() => pollState());

    assert.strictEqual(
      await page.locator("#analysisProgressLabel").textContent(),
      "Combined workbook failed: Unknown reference override: typo. Completed outputs: Video: C:\\reports\\video",
    );
  } finally {
    await page.close();
  }
}

async function main() {
  const staticRoot = path.join(uiRoot, "static");
  const server = http.createServer((request, response) => {
    const pathname = new URL(request.url, "http://127.0.0.1").pathname;
    const relativePath = pathname === "/" ? "index.html" : pathname.replace(/^\/static\//, "");
    const filePath = path.join(staticRoot, relativePath);
    if (!filePath.startsWith(staticRoot) || !fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
      response.writeHead(404).end("Not found");
      return;
    }
    response.writeHead(200, { "Content-Type": contentType(filePath) });
    fs.createReadStream(filePath).pipe(response);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  const browser = await launchBrowser();
  const failures = [];
  for (const [name, scenario] of [
    ["home branding responsive", homeBrandingResponsive],
    ["invalid source error remains contained", invalidSourceErrorStaysContained],
    ["discovery and accessibility", staleDiscoveryAndGroupAccessibility],
    ["submission lock and payloads", submissionLockAndPayloads],
    ["workflow failure detail", workflowFailureDetail],
    ["responsive rendering", responsiveSmoke],
    ["text grouping preflight", textGroupingPreflight],
    ["sidecarless manifest selection", sidecarlessManifestSelection],
  ]) {
    try {
      await scenario(browser, origin);
    } catch (error) {
      failures.push(`${name}: ${error.stack || error.message}`);
    }
  }
  await browser.close();
  await new Promise((resolve) => server.close(resolve));
  if (failures.length) {
    throw new Error(failures.join("\n\n"));
  }
  console.log("analysis browser interaction checks passed");
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exitCode = error instanceof BrowserAutomationUnavailable ? 77 : 1;
});
