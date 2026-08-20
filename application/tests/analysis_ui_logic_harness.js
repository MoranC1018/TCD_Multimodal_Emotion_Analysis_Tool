"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const sourcePath = process.argv[1] || process.argv[2];
if (!sourcePath) {
  throw new Error("Pass the production app.js path to this harness.");
}

const source = fs.readFileSync(sourcePath, "utf8");
const startMarker = "// ANALYSIS_UI_LOGIC_START";
const endMarker = "// ANALYSIS_UI_LOGIC_END";
const start = source.indexOf(startMarker);
const end = source.indexOf(endMarker);
assert.ok(start >= 0 && end > start, "Production analysis logic markers were not found.");

const logic = source.slice(start + startMarker.length, end);
const context = { console };
vm.createContext(context);
vm.runInContext(`${logic}\nthis.analysisTestApi = {
  analysisSpeakerGroupIssues,
  analysisRunGateReasons,
  resolveAnalysisHydration,
  analysisGroupAccessibleLabels,
  chooseAnalysisFocusKey,
  parseFiniteReferenceOverridesText,
  createAnalysisAsyncOperation,
  beginAnalysisAsyncOperation,
  isAnalysisAsyncOperationCurrent,
  invalidateAnalysisAsyncOperation,
  finishAnalysisAsyncOperation,
  buildAnalysisWorkflowRequest,
};`, context);

const {
  analysisSpeakerGroupIssues,
  analysisRunGateReasons,
  resolveAnalysisHydration,
  analysisGroupAccessibleLabels,
  chooseAnalysisFocusKey,
  parseFiniteReferenceOverridesText,
  createAnalysisAsyncOperation,
  beginAnalysisAsyncOperation,
  isAnalysisAsyncOperationCurrent,
  invalidateAnalysisAsyncOperation,
  finishAnalysisAsyncOperation,
  buildAnalysisWorkflowRequest,
} = context.analysisTestApi;

const speakers = [
  { key: "speaker_a", name: "Speaker A" },
  { key: "speaker_b", name: "Speaker B" },
  { key: "speaker_extra", name: "Speaker Extra" },
];
const incompleteGroups = [{ id: "group-1", name: "Group 1", speakerKeys: ["speaker_a", "speaker_b"] }];
assert.deepStrictEqual(
  Array.from(analysisSpeakerGroupIssues(speakers, incompleteGroups)),
  ["Assign every discovered speaker to one group. Unassigned: Speaker Extra."],
);
assert.ok(
  analysisSpeakerGroupIssues(speakers, [
    { id: "group-1", name: "Group 1", speakerKeys: ["speaker_a", "speaker_extra"] },
    { id: "group-2", name: "Group 2", speakerKeys: ["speaker_b", "speaker_extra"] },
  ]).some((message) => message.includes("assigned more than once")),
);

const importModality = [{ name: "audio", sourceMethod: "import", sourcePath: "C:\\reports" }];
const workbookOffReasons = analysisRunGateReasons({
  modalities: importModality,
  outputRoot: "C:\\output",
  writeCombinedWorkbook: false,
  discoverySignature: "",
  currentSignature: JSON.stringify(importModality),
  speakers: [],
  groups: [],
  defaultReferenceText: "not-a-number",
  referenceOverridesText: '{"bad": false}',
});
assert.deepStrictEqual(Array.from(workbookOffReasons), []);

const workbookOnReasons = Array.from(analysisRunGateReasons({
  modalities: importModality,
  outputRoot: "C:\\output",
  writeCombinedWorkbook: true,
  discoverySignature: "stale",
  currentSignature: JSON.stringify(importModality),
  speakers,
  groups: incompleteGroups,
  defaultReferenceText: "not-a-number",
  referenceOverridesText: '{"bad": false}',
}));
assert.ok(workbookOnReasons.some((message) => message.includes("Discover speakers")));
assert.ok(workbookOnReasons.some((message) => message.includes("Unassigned")));
assert.ok(workbookOnReasons.some((message) => message.includes("Default reference")));
assert.ok(workbookOnReasons.some((message) => message.includes("JSON numbers")));

assert.deepStrictEqual(
  JSON.parse(JSON.stringify(resolveAnalysisHydration("C:\\old", "C:\\new", true))),
  { enabled: true, sourcePath: "C:\\new", sourceMethod: "run" },
);
assert.deepStrictEqual(
  JSON.parse(JSON.stringify(resolveAnalysisHydration("C:\\old", "", true))),
  { enabled: false, sourcePath: "", sourceMethod: "run" },
);
assert.deepStrictEqual(
  JSON.parse(JSON.stringify(resolveAnalysisHydration("", "C:\\text", true, "import"))),
  { enabled: true, sourcePath: "C:\\text", sourceMethod: "import" },
);
assert.strictEqual(resolveAnalysisHydration("C:\\manual", "C:\\suggested", false), null);
assert.deepStrictEqual(
  JSON.parse(JSON.stringify(analysisGroupAccessibleLabels("Renamed group", "Speaker A"))),
  { remove: "Remove Renamed group", assign: "Assign Speaker A to Renamed group" },
);
assert.strictEqual(
  chooseAnalysisFocusKey("speaker:g1:a", "speaker:g1:b", ["speaker:g1:a", "speaker:g1:b"]),
  "speaker:g1:a",
);
assert.strictEqual(
  chooseAnalysisFocusKey("missing", "speaker:g1:b", ["speaker:g1:b"]),
  "speaker:g1:b",
);

assert.deepStrictEqual(
  JSON.parse(JSON.stringify(parseFiniteReferenceOverridesText('{"Audio - Group 1": 1.25}'))),
  { "Audio - Group 1": 1.25 },
);
for (const invalidValue of ["null", "false", "true", '"1"', "[]", "{}"] ) {
  assert.throws(
    () => parseFiniteReferenceOverridesText(`{"metric": ${invalidValue}}`),
    /finite JSON numbers/,
  );
}

const operation = createAnalysisAsyncOperation();
const first = beginAnalysisAsyncOperation(operation, "source-a");
assert.ok(first);
assert.strictEqual(beginAnalysisAsyncOperation(operation, "source-a"), null, "Repeated start must be ignored.");
invalidateAnalysisAsyncOperation(operation);
const second = beginAnalysisAsyncOperation(operation, "source-b");
assert.ok(second);
assert.strictEqual(isAnalysisAsyncOperationCurrent(operation, first, "source-a"), false);
assert.strictEqual(isAnalysisAsyncOperationCurrent(operation, second, "source-b"), true);
assert.strictEqual(finishAnalysisAsyncOperation(operation, first), false, "Stale completion must be ignored.");
assert.strictEqual(finishAnalysisAsyncOperation(operation, second), true);

const request = buildAnalysisWorkflowRequest({
  modalities: importModality,
  outputRoot: "C:\\output",
  writeCombinedWorkbook: false,
  defaultReference: 0,
  referenceOverrides: {},
  speakerGroups: incompleteGroups,
  writeGraphs: true,
  includeLogscale: true,
  includeLandmarks: false,
  includeTiming: false,
  excludeGeometry: false,
});
assert.deepStrictEqual(Array.from(request.speakerGroups), []);
assert.strictEqual(request.writeGraphs, false);
assert.strictEqual(request.includeLogscale, false);
assert.strictEqual(Object.prototype.hasOwnProperty.call(request, "text"), false);

const mixedRequest = buildAnalysisWorkflowRequest({
  modalities: [
    ...importModality,
    { name: "imotions", sourceMethod: "run", sourcePath: "C:\\imotions" },
    { name: "text", sourceMethod: "import", sourcePath: "C:\\text" },
  ],
  outputRoot: "C:\\output",
  writeCombinedWorkbook: true,
  defaultReference: 0,
  referenceOverrides: {},
  speakerGroups: [{ id: "group-1", name: "Group 1", speakerKeys: ["speaker_a"] }],
  writeGraphs: true,
  includeLogscale: true,
  includeLandmarks: true,
  includeTiming: false,
  excludeGeometry: false,
});
assert.strictEqual(mixedRequest.writeGraphs, true);
assert.strictEqual(mixedRequest.includeLogscale, true);
assert.strictEqual(mixedRequest.speakerGroups.length, 1);
assert.strictEqual(mixedRequest.modalities[2].name, "text");
assert.strictEqual(mixedRequest.modalities[2].sourceMethod, "import");

console.log("analysis UI behavior checks passed");
