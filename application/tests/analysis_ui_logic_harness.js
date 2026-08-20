"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const sourcePath = process.argv[2] || process.argv[1];
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
  createAnalysisProfileDraft,
  analysisProfileIssues,
  buildAnalysisProfilePayload,
  resolveAnalysisProfilePreview,
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
  createAnalysisProfileDraft,
  analysisProfileIssues,
  buildAnalysisProfilePayload,
  resolveAnalysisProfilePreview,
} = context.analysisTestApi;

const profileContext = {
  sourceManifest: "C:\\run\\source_manifest.json",
  sourceManifestSha256: "a".repeat(64),
  metadataFields: [
    { name: "Country", values: ["Ireland", "Japan"] },
    { name: "Wave", values: ["First", "Second"] },
  ],
  speakers: [
    { id: "researcher-alpha", name: "Researcher Alpha", sourceIds: ["source-0001", "source-0002"] },
    { id: "researcher-beta", name: "Researcher Beta", sourceIds: ["source-0003"] },
  ],
  sources: [
    { id: "source-0001", title: "First", speakerId: "researcher-alpha", speaker: "Researcher Alpha", metadata: { Country: "Japan", Wave: "Second" } },
    { id: "source-0002", title: "Second", speakerId: "researcher-alpha", speaker: "Researcher Alpha", metadata: { Country: "Ireland", Wave: "First" } },
    { id: "source-0003", title: "Third", speakerId: "researcher-beta", speaker: "Researcher Beta", metadata: { Country: "Ireland", Wave: "Second" } },
  ],
};
const profileDraft = createAnalysisProfileDraft(profileContext);
profileDraft.sortFields = ["Country", "Wave"];
profileDraft.automaticGroupField = "Country";
profileDraft.manualGroups = [
  { id: "manual-1", name: "Interview set", members: [
    { type: "speaker", id: "researcher-alpha" },
    { type: "source", id: "source-0003" },
  ] },
];
assert.deepStrictEqual(Array.from(analysisProfileIssues(profileContext, profileDraft)), []);
const profilePayload = buildAnalysisProfilePayload(profileContext, profileDraft);
assert.deepStrictEqual(Array.from(profilePayload.sort_fields), ["Country", "Wave"]);
assert.strictEqual(profilePayload.automatic_group_field, "Country");
assert.strictEqual(profilePayload.manual_groups[0].members[0].type, "speaker");
const preview = resolveAnalysisProfilePreview(profileContext, profileDraft);
assert.deepStrictEqual(Array.from(preview.orderedSourceIds), ["source-0002", "source-0003", "source-0001"]);
assert.strictEqual(preview.groups[0].sourceIds.length, 3);
const duplicateDraft = createAnalysisProfileDraft(profileContext);
duplicateDraft.manualGroups = [
  { id: "one", name: "One", members: [{ type: "speaker", id: "researcher-alpha" }] },
  { id: "two", name: "Two", members: [{ type: "source", id: "source-0002" }] },
];
assert.ok(analysisProfileIssues(profileContext, duplicateDraft).some((message) => message.includes("source-0002") && message.includes("more than one")));
const automaticTextSplitDraft = createAnalysisProfileDraft(profileContext);
automaticTextSplitDraft.automaticGroupField = "Country";
assert.ok(
  analysisProfileIssues(profileContext, automaticTextSplitDraft, true)
    .some((message) => message.includes("Text is speaker-level") && message.includes("Researcher Alpha")),
);
assert.deepStrictEqual(
  Array.from(analysisProfileIssues(profileContext, automaticTextSplitDraft, false)),
  [],
  "Source-level automatic grouping remains valid when Text is disabled.",
);
const manualTextSplitDraft = createAnalysisProfileDraft(profileContext);
manualTextSplitDraft.manualGroups = [
  { id: "first-video", name: "First video", members: [{ type: "source", id: "source-0001" }] },
];
assert.ok(
  analysisProfileIssues(profileContext, manualTextSplitDraft, true)
    .some((message) => message.includes("Text is speaker-level") && message.includes("Researcher Alpha")),
);
const hiddenMemberDraft = createAnalysisProfileDraft(profileContext);
hiddenMemberDraft.metadataFilters.Country = ["Ireland"];
hiddenMemberDraft.manualGroups = [
  { id: "hidden", name: "Hidden", members: [{ type: "source", id: "source-0001" }] },
];
assert.ok(analysisProfileIssues(profileContext, hiddenMemberDraft).some((message) => message.includes("unknown source") && message.includes("source-0001")));
const blankMetadataContext = {
  ...profileContext,
  metadataFields: [...profileContext.metadataFields, { name: "Optional note", values: [] }],
};
const blankMetadataDraft = createAnalysisProfileDraft(blankMetadataContext);
assert.deepStrictEqual(
  Array.from(analysisProfileIssues(blankMetadataContext, blankMetadataDraft)),
  [],
  "An entirely blank optional metadata column must not block the default profile.",
);
assert.deepStrictEqual(
  JSON.parse(JSON.stringify(buildAnalysisProfilePayload(blankMetadataContext, blankMetadataDraft).metadata_filters)),
  {},
);
const exactValueContext = {
  ...profileContext,
  metadataFields: [{ name: "Country", values: ["ireland", "Ireland"] }],
  sources: [
    { ...profileContext.sources[0], metadata: { Country: "ireland" } },
    { ...profileContext.sources[1], metadata: { Country: "Ireland" } },
  ],
  speakers: [{ id: "researcher-alpha", name: "Researcher Alpha", sourceIds: ["source-0001", "source-0002"] }],
};
const exactValueDraft = createAnalysisProfileDraft(exactValueContext);
exactValueDraft.sortFields = ["Country"];
exactValueDraft.automaticGroupField = "Country";
const exactValuePreview = resolveAnalysisProfilePreview(exactValueContext, exactValueDraft);
assert.deepStrictEqual(Array.from(exactValuePreview.orderedSourceIds), ["source-0002", "source-0001"]);
assert.deepStrictEqual(Array.from(exactValuePreview.groups, (group) => group.name), ["Ireland", "ireland"]);

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
assert.ok(workbookOnReasons.some((message) => message.includes("Load source metadata")));
assert.ok(workbookOnReasons.some((message) => message.includes("Unassigned")));
assert.ok(workbookOnReasons.some((message) => message.includes("Default reference")));
assert.ok(workbookOnReasons.some((message) => message.includes("JSON numbers")));

const textSplitModalities = [
  importModality[0],
  { name: "text", sourceMethod: "import", sourcePath: "C:\\text-results" },
];
const textSplitReasons = Array.from(analysisRunGateReasons({
  modalities: textSplitModalities,
  outputRoot: "C:\\output",
  writeCombinedWorkbook: true,
  discoverySignature: "current",
  currentSignature: "current",
  profileContext,
  profileDraft: automaticTextSplitDraft,
  defaultReferenceText: "0",
  referenceOverridesText: "{}",
}));
assert.ok(textSplitReasons.some((message) => message.includes("Text is speaker-level")));

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

const profiledRequest = buildAnalysisWorkflowRequest({
  modalities: importModality,
  outputRoot: "C:\\output",
  writeCombinedWorkbook: true,
  defaultReference: 0,
  referenceOverrides: {},
  speakerGroups: incompleteGroups,
  analysisProfile: profilePayload,
  writeGraphs: false,
  includeLogscale: false,
  includeLandmarks: false,
  includeTiming: false,
  excludeGeometry: false,
});
assert.deepStrictEqual(Array.from(profiledRequest.speakerGroups), []);
assert.strictEqual(profiledRequest.analysisProfile.source_manifest.sha256, "a".repeat(64));

console.log("analysis UI behavior checks passed");
