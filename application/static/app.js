// DOM handles are collected up front so missing markup fails clearly during
// development instead of being discovered deep inside a click handler.
const screens = Array.from(document.querySelectorAll(".screen"));
const stepButtons = Array.from(document.querySelectorAll("[data-screen-target]"));
const modeHome = document.querySelector("#modeHome");
const workflowApp = document.querySelector("#workflowApp");
const moduleTitle = document.querySelector("#moduleTitle");
const procurementSteps = document.querySelector("#procurementSteps");
const backToModesButton = document.querySelector("#backToModesButton");
const openProcurementButton = document.querySelector("#openProcurementButton");
const openProcessingButton = document.querySelector("#openProcessingButton");
const openAnalysisButton = document.querySelector("#openAnalysisButton");
const homeStatusLabel = document.querySelector("#homeStatusLabel");
const openSettingsButton = document.querySelector("#openSettingsButton");
const settingsDialog = document.querySelector("#settingsDialog");
const closeSettingsButton = document.querySelector("#closeSettingsButton");
const saveSettingsButton = document.querySelector("#saveSettingsButton");
const revokeAccessButton = document.querySelector("#revokeAccessButton");
const youtubeApiKeyInput = document.querySelector("#youtubeApiKeyInput");
const huggingFaceTokenInput = document.querySelector("#huggingFaceTokenInput");
const youtubeApiKeyStatus = document.querySelector("#youtubeApiKeyStatus");
const huggingFaceTokenStatus = document.querySelector("#huggingFaceTokenStatus");
const clearYoutubeApiKeyToggle = document.querySelector("#clearYoutubeApiKeyToggle");
const clearHuggingFaceTokenToggle = document.querySelector("#clearHuggingFaceTokenToggle");
const youtubeCookiesBrowserSelect = document.querySelector("#youtubeCookiesBrowserSelect");
const resourceLimitsEnabledToggle = document.querySelector("#resourceLimitsEnabledToggle");
const maxCpuPercentInput = document.querySelector("#maxCpuPercentInput");
const maxCpuCoresInput = document.querySelector("#maxCpuCoresInput");
const maxGpuPercentInput = document.querySelector("#maxGpuPercentInput");
const ramLimitModeSelect = document.querySelector("#ramLimitModeSelect");
const maxRamPercentField = document.querySelector("#maxRamPercentField");
const maxRamPercentInput = document.querySelector("#maxRamPercentInput");
const maxRamGbField = document.querySelector("#maxRamGbField");
const maxRamGbInput = document.querySelector("#maxRamGbInput");
const nativeThreadsInput = document.querySelector("#nativeThreadsInput");
const resourcePollSecondsInput = document.querySelector("#resourcePollSecondsInput");
const resourceCapabilitiesText = document.querySelector("#resourceCapabilitiesText");
const eulaPathInput = document.querySelector("#eulaPathInput");
const guidedWorkflowToggle = document.querySelector("#guidedWorkflowToggle");
const workflowPlannerBody = document.querySelector("#workflowPlannerBody");
const workflowProcurementToggle = document.querySelector("#workflowProcurementToggle");
const workflowProcessingToggle = document.querySelector("#workflowProcessingToggle");
const workflowAnalysisToggle = document.querySelector("#workflowAnalysisToggle");
const workflowFaceToggle = document.querySelector("#workflowFaceToggle");
const workflowAudioToggle = document.querySelector("#workflowAudioToggle");
const workflowTextToggle = document.querySelector("#workflowTextToggle");
const workflowFaceMethod = document.querySelector("#workflowFaceMethod");
const workflowAudioMethod = document.querySelector("#workflowAudioMethod");
const workflowTextMethod = document.querySelector("#workflowTextMethod");
const workflowFaceImportPath = document.querySelector("#workflowFaceImportPath");
const workflowAudioImportPath = document.querySelector("#workflowAudioImportPath");
const workflowTextImportPath = document.querySelector("#workflowTextImportPath");
const browseWorkflowFaceButton = document.querySelector("#browseWorkflowFaceButton");
const browseWorkflowAudioButton = document.querySelector("#browseWorkflowAudioButton");
const browseWorkflowTextButton = document.querySelector("#browseWorkflowTextButton");
const startGuidedWorkflowButton = document.querySelector("#startGuidedWorkflowButton");
const openFaceProcessingButton = document.querySelector("#openFaceProcessingButton");
const openAudioProcessingButton = document.querySelector("#openAudioProcessingButton");
const openTextProcessingButton = document.querySelector("#openTextProcessingButton");
const faceImportToggle = document.querySelector("#faceImportToggle");
const faceImportPathInput = document.querySelector("#faceImportPathInput");
const browseFaceImportButton = document.querySelector("#browseFaceImportButton");
const audioImportHubToggle = document.querySelector("#audioImportHubToggle");
const audioImportHubPathInput = document.querySelector("#audioImportHubPathInput");
const browseAudioImportHubButton = document.querySelector("#browseAudioImportHubButton");
const textImportToggle = document.querySelector("#textImportToggle");
const textImportPathInput = document.querySelector("#textImportPathInput");
const browseTextImportButton = document.querySelector("#browseTextImportButton");
const continueToAnalysisButton = document.querySelector("#continueToAnalysisButton");
const backToProcessingButton = document.querySelector("#backToProcessingButton");
const backToAudioInputButton = document.querySelector("#backToAudioInputButton");
const sourcePathInput = document.querySelector("#sourcePathInput");
const outputRootInput = document.querySelector("#outputRootInput");
const browseOutputButton = document.querySelector("#browseOutputButton");
const sourcePickerDialog = document.querySelector("#sourcePickerDialog");
const closeSourcePickerButton = document.querySelector("#closeSourcePickerButton");
const chooseSourceFolderButton = document.querySelector("#chooseSourceFolderButton");
const chooseSourceFileButton = document.querySelector("#chooseSourceFileButton");
const scanButton = document.querySelector("#scanButton");
const rescanButton = document.querySelector("#rescanButton");
const toRunButton = document.querySelector("#toRunButton");
const runButton = document.querySelector("#runButton");
const manualRunButton = document.querySelector("#manualRunButton");
const manualBackButton = document.querySelector("#manualBackButton");
const backToReviewButton = document.querySelector("#backToReviewButton");
const stopButton = document.querySelector("#stopButton");
const sortSelect = document.querySelector("#sortSelect");
const catalogMetadataControls = document.querySelector("#catalogMetadataControls");
const catalogFilterField = document.querySelector("#catalogFilterField");
const catalogFilterText = document.querySelector("#catalogFilterText");
const catalogSortField = document.querySelector("#catalogSortField");
const catalogSortDirection = document.querySelector("#catalogSortDirection");
const selectVisibleSourcesButton = document.querySelector("#selectVisibleSourcesButton");
const clearVisibleSourcesButton = document.querySelector("#clearVisibleSourcesButton");
const statusLabel = document.querySelector("#statusLabel");
const scanSummary = document.querySelector("#scanSummary");
const scanTabList = document.querySelector("#scanTabList");
const toggleAllSpeakersButton = document.querySelector("#toggleAllSpeakersButton");
const speakerSelectionSummary = document.querySelector("#speakerSelectionSummary");
const speakerTitle = document.querySelector("#speakerTitle");
const videoGroups = document.querySelector("#videoGroups");
const manualVideoList = document.querySelector("#manualVideoList");
const manualSummary = document.querySelector("#manualSummary");
const modeInputs = Array.from(document.querySelectorAll("input[name='mode']"));
const standardSettings = document.querySelector("#standardSettings");
const focusSettings = document.querySelector("#focusSettings");
const focusGapInput = document.querySelector("#focusGapInput");
const cleanSpeakerSettings = document.querySelector("#cleanSpeakerSettings");
const maxSegmentInput = document.querySelector("#maxSegmentInput");
const samplePercentInput = document.querySelector("#samplePercentInput");
const betaOutputModeInputs = Array.from(document.querySelectorAll("input[name='betaOutputMode']"));
const betaPercentageSettings = document.querySelector("#betaPercentageSettings");
const betaPercentInput = document.querySelector("#betaPercentInput");
const betaMinCleanInput = document.querySelector("#betaMinCleanInput");
const betaMaxSegmentSettings = document.querySelector("#betaMaxSegmentSettings");
const betaMaxSegmentInput = document.querySelector("#betaMaxSegmentInput");
const betaGapInput = document.querySelector("#betaGapInput");
const betaIdentityStillsInput = document.querySelector("#betaIdentityStillsInput");
const betaScanFpsInput = document.querySelector("#betaScanFpsInput");
const betaValidationFpsInput = document.querySelector("#betaValidationFpsInput");
const betaMaxDownloadHeightInput = document.querySelector("#betaMaxDownloadHeightInput");
const betaOnlyVideoIdsInput = document.querySelector("#betaOnlyVideoIdsInput");
const betaRandomOneToggle = document.querySelector("#betaRandomOneToggle");
const betaRandomSeedInput = document.querySelector("#betaRandomSeedInput");
const betaFaceConfidenceInput = document.querySelector("#betaFaceConfidenceInput");
const betaSpeakerConfidenceInput = document.querySelector("#betaSpeakerConfidenceInput");
const betaWorkerCountInput = document.querySelector("#betaWorkerCountInput");
const betaDeviceSelect = document.querySelector("#betaDeviceSelect");
const betaParallelDetectorToggle = document.querySelector("#betaParallelDetectorToggle");
const betaKeepDebugToggle = document.querySelector("#betaKeepDebugToggle");
const betaReferenceAudioInput = document.querySelector("#betaReferenceAudioInput");
const betaIsolatedModeToggle = document.querySelector("#betaIsolatedModeToggle");
const betaSkipCompletedToggle = document.querySelector("#betaSkipCompletedToggle");
const betaSkipFirstInput = document.querySelector("#betaSkipFirstInput");
const betaCooldownInput = document.querySelector("#betaCooldownInput");
const checkBetaReadinessButton = document.querySelector("#checkBetaReadinessButton");
const betaReadinessList = document.querySelector("#betaReadinessList");
const runProgressView = document.querySelector("#runProgressView");
const manualRunView = document.querySelector("#manualRunView");
const runTitle = document.querySelector("#runTitle");
const runSubtitle = document.querySelector("#runSubtitle");
const progressBar = document.querySelector("#progressBar");
const progressLabel = document.querySelector("#progressLabel");
const procurementNextStep = document.querySelector("#procurementNextStep");
const procurementNextTitle = document.querySelector("#procurementNextTitle");
const procurementNextCopy = document.querySelector("#procurementNextCopy");
const goToProcessingButton = document.querySelector("#goToProcessingButton");
const audioModeInputs = Array.from(document.querySelectorAll("input[name='audioMode']"));
const audioModeToggle = document.querySelector("#audioModeToggle");
const audioOptionsPanel = document.querySelector(".audio-options-panel");
const audioSourcePathInput = document.querySelector("#audioSourcePathInput");
const audioSourcePathLabel = document.querySelector("#audioSourcePathLabel");
const audioOutputRootInput = document.querySelector("#audioOutputRootInput");
const browseAudioFolderButton = document.querySelector("#browseAudioFolderButton");
const browseAudioVideoButton = document.querySelector("#browseAudioVideoButton");
const browseAudioOutputButton = document.querySelector("#browseAudioOutputButton");
const runAudioButton = document.querySelector("#runAudioButton");
const stopAudioButton = document.querySelector("#stopAudioButton");
const audioImportToggle = document.querySelector("#audioImportToggle");
const audioWindowSecondsInput = document.querySelector("#audioWindowSecondsInput");
const audioStrideSecondsInput = document.querySelector("#audioStrideSecondsInput");
const audioFeatureSetSelect = document.querySelector("#audioFeatureSetSelect");
const audioDeviceSelect = document.querySelector("#audioDeviceSelect");
const audioEmotionsToggle = document.querySelector("#audioEmotionsToggle");
const audioKeepTempToggle = document.querySelector("#audioKeepTempToggle");
const audioDebugToggle = document.querySelector("#audioDebugToggle");
const audioStopOnErrorToggle = document.querySelector("#audioStopOnErrorToggle");
const audioCatalogSelection = document.querySelector("#audioCatalogSelection");
const audioCatalogSelectionSummary = document.querySelector("#audioCatalogSelectionSummary");
const audioCatalogFilterField = document.querySelector("#audioCatalogFilterField");
const audioCatalogFilterText = document.querySelector("#audioCatalogFilterText");
const audioCatalogSortField = document.querySelector("#audioCatalogSortField");
const audioCatalogSortDirection = document.querySelector("#audioCatalogSortDirection");
const audioSelectVisibleSourcesButton = document.querySelector("#audioSelectVisibleSourcesButton");
const audioClearVisibleSourcesButton = document.querySelector("#audioClearVisibleSourcesButton");
const audioCatalogSourceList = document.querySelector("#audioCatalogSourceList");
const audioProgressBar = document.querySelector("#audioProgressBar");
const audioProgressLabel = document.querySelector("#audioProgressLabel");
const audioNextTitle = document.querySelector("#audioNextTitle");
const audioNextCopy = document.querySelector("#audioNextCopy");
const audioNextStep = document.querySelector("#audioNextStep");
const audioToAnalysisButton = document.querySelector("#audioToAnalysisButton");
const analysisOutputRootInput = document.querySelector("#analysisOutputRootInput");
const browseAnalysisOutputButton = document.querySelector("#browseAnalysisOutputButton");
const analysisImotionsEnabled = document.querySelector("#analysisImotionsEnabled");
const analysisImotionsSourcePath = document.querySelector("#analysisImotionsSourcePath");
const analysisImotionsMethodInputs = Array.from(document.querySelectorAll("input[name='analysisImotionsSourceMethod']"));
const browseAnalysisImotionsSource = document.querySelector("#browseAnalysisImotionsSource");
const analysisAudioEnabled = document.querySelector("#analysisAudioEnabled");
const analysisAudioSourcePath = document.querySelector("#analysisAudioSourcePath");
const analysisAudioMethodInputs = Array.from(document.querySelectorAll("input[name='analysisAudioSourceMethod']"));
const browseAnalysisAudioSource = document.querySelector("#browseAnalysisAudioSource");
const analysisTextEnabled = document.querySelector("#analysisTextEnabled");
const analysisTextSourcePath = document.querySelector("#analysisTextSourcePath");
const analysisTextMethodInputs = Array.from(document.querySelectorAll("input[name='analysisTextSourceMethod']"));
const browseAnalysisTextSource = document.querySelector("#browseAnalysisTextSource");
const analysisSourceManifestInput = document.querySelector("#analysisSourceManifestInput");
const browseAnalysisSourceManifestButton = document.querySelector("#browseAnalysisSourceManifestButton");
const discoverAnalysisSpeakersButton = document.querySelector("#discoverAnalysisSpeakersButton");
const analysisSpeakerDiscoveryStatus = document.querySelector("#analysisSpeakerDiscoveryStatus");
const analysisGroupWarningStatus = document.querySelector("#analysisGroupWarningStatus");
const analysisSpeakerGroups = document.querySelector("#analysisSpeakerGroups");
const addAnalysisSpeakerGroupButton = document.querySelector("#addAnalysisSpeakerGroupButton");
const openAnalysisCustomizeButton = document.querySelector("#openAnalysisCustomizeButton");
const backFromAnalysisCustomizeButton = document.querySelector("#backFromAnalysisCustomizeButton");
const saveAnalysisCustomizationButton = document.querySelector("#saveAnalysisCustomizationButton");
const analysisProfileSummary = document.querySelector("#analysisProfileSummary");
const analysisSortFields = document.querySelector("#analysisSortFields");
const analysisAutomaticGroupField = document.querySelector("#analysisAutomaticGroupField");
const analysisMetadataFilters = document.querySelector("#analysisMetadataFilters");
const analysisProfilePreview = document.querySelector("#analysisProfilePreview");
const analysisWriteCombinedToggle = document.querySelector("#analysisWriteCombinedToggle");
const analysisConstructComparisonToggle = document.querySelector("#analysisConstructComparisonToggle");
const analysisProbabilitySheetsToggle = document.querySelector("#analysisProbabilitySheetsToggle");
const analysisConfidenceLevelInput = document.querySelector("#analysisConfidenceLevelInput");
const analysisHeadlinePolicySelect = document.querySelector("#analysisHeadlinePolicySelect");
const analysisDefaultReferenceInput = document.querySelector("#analysisDefaultReferenceInput");
const analysisReferenceOverridesInput = document.querySelector("#analysisReferenceOverridesInput");
const analysisGraphsToggle = document.querySelector("#analysisGraphsToggle");
const analysisLogscaleToggle = document.querySelector("#analysisLogscaleToggle");
const analysisGraphsOption = document.querySelector("#analysisGraphsOption");
const analysisLogscaleOption = document.querySelector("#analysisLogscaleOption");
const analysisFaceAdvanced = document.querySelector("#analysisFaceAdvanced");
const analysisLandmarksToggle = document.querySelector("#analysisLandmarksToggle");
const analysisTimingToggle = document.querySelector("#analysisTimingToggle");
const analysisExcludeGeometryToggle = document.querySelector("#analysisExcludeGeometryToggle");
const runAnalysisButton = document.querySelector("#runAnalysisButton");
const analysisRunGateMessages = document.querySelector("#analysisRunGateMessages");
const stopAnalysisButton = document.querySelector("#stopAnalysisButton");
const backToAnalysisInputButton = document.querySelector("#backToAnalysisInputButton");
const analysisProgressBar = document.querySelector("#analysisProgressBar");
const analysisProgressLabel = document.querySelector("#analysisProgressLabel");
const segmentDialog = document.querySelector("#segmentDialog");
const segmentDialogTitle = document.querySelector("#segmentDialogTitle");
const segmentDialogMeta = document.querySelector("#segmentDialogMeta");
const closeSegmentDialogButton = document.querySelector("#closeSegmentDialogButton");
const youtubePlayer = document.querySelector("#youtubePlayer");
const manualPlayer = document.querySelector("#manualPlayer");
const timeline = document.querySelector("#timeline");
const segmentsLayer = document.querySelector("#segmentsLayer");
const previewLayer = document.querySelector("#previewLayer");
const timelinePlayhead = document.querySelector("#timelinePlayhead");
const tickLayer = document.querySelector("#tickLayer");
const playbackTimeLabel = document.querySelector("#playbackTimeLabel");
const segmentStartInput = document.querySelector("#segmentStartInput");
const segmentEndInput = document.querySelector("#segmentEndInput");
const useStartButton = document.querySelector("#useStartButton");
const useEndButton = document.querySelector("#useEndButton");
const addSegmentButton = document.querySelector("#addSegmentButton");
const deleteSegmentButton = document.querySelector("#deleteSegmentButton");
const segmentList = document.querySelector("#segmentList");
const manualTotal = document.querySelector("#manualTotal");
const manualShare = document.querySelector("#manualShare");
const manualCount = document.querySelector("#manualCount");

const PROGRESS_POLL_INTERVAL_MS = 1000;
const API_TIMEOUT_MS = 15000;
const launcherToken = document.querySelector("meta[name='launcher-token']")?.content || "";
let progressPollTimer = null;
let analysisWarningAnnouncementTimer = null;

const analysisImotionsControls = {
  name: "imotions",
  label: "Video / iMotions",
  enabled: analysisImotionsEnabled,
  source: analysisImotionsSourcePath,
  methodInputs: analysisImotionsMethodInputs,
  browse: browseAnalysisImotionsSource,
};
const analysisAudioControls = {
  name: "audio",
  label: "Audio",
  enabled: analysisAudioEnabled,
  source: analysisAudioSourcePath,
  methodInputs: analysisAudioMethodInputs,
  browse: browseAnalysisAudioSource,
};
const analysisTextControls = {
  name: "text",
  label: "Text",
  enabled: analysisTextEnabled,
  source: analysisTextSourcePath,
  methodInputs: analysisTextMethodInputs,
  browse: browseAnalysisTextSource,
};
const analysisImplementedControls = [
  analysisImotionsControls,
  analysisAudioControls,
  analysisTextControls,
];

// ANALYSIS_UI_LOGIC_START
// This block is intentionally DOM-free so the release tests can execute the
// same validation and request rules used by the browser UI.
function parseFiniteReferenceOverridesText(text) {
  const cleanText = String(text || "").trim();
  if (!cleanText) {
    return {};
  }
  let parsed;
  try {
    parsed = JSON.parse(cleanText);
  } catch (_) {
    throw new Error("Reference overrides must be a JSON object.");
  }
  if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
    throw new Error("Reference overrides must be a JSON object.");
  }
  const overrides = {};
  Object.entries(parsed).forEach(([key, value]) => {
    const cleanKey = key.trim();
    if (!cleanKey || typeof value !== "number" || !Number.isFinite(value)) {
      throw new Error("Reference override names must be non-empty and values must be finite JSON numbers.");
    }
    overrides[cleanKey] = value;
  });
  return overrides;
}

function analysisSpeakerGroupIssues(speakers, groups) {
  const discoveredNames = new Map(
    speakers.map((speaker) => [speaker.key, speaker.name || speaker.key]),
  );
  const issues = [];
  const groupNames = new Set();
  const assignments = new Map();

  if (!groups.length) {
    issues.push("Add at least one speaker group.");
  }
  groups.forEach((group, index) => {
    const displayName = String(group.name || "").trim();
    const normalizedName = displayName.toLocaleLowerCase();
    if (!displayName) {
      issues.push(`Group ${index + 1} needs a name.`);
    } else if (groupNames.has(normalizedName)) {
      issues.push(`Speaker group names must be unique; duplicate: ${displayName}.`);
    } else {
      groupNames.add(normalizedName);
    }
    if (!Array.isArray(group.speakerKeys) || !group.speakerKeys.length) {
      issues.push(`${displayName || `Group ${index + 1}`} needs at least one speaker.`);
      return;
    }
    group.speakerKeys.forEach((speakerKey) => {
      if (!discoveredNames.has(speakerKey)) {
        issues.push(`${displayName || `Group ${index + 1}`} contains an unknown speaker: ${speakerKey}.`);
        return;
      }
      assignments.set(speakerKey, (assignments.get(speakerKey) || 0) + 1);
    });
  });

  const repeated = speakers
    .filter((speaker) => (assignments.get(speaker.key) || 0) > 1)
    .map((speaker) => speaker.name || speaker.key);
  if (repeated.length) {
    issues.push(`Each speaker can be assigned only once. Speakers assigned more than once: ${repeated.join(", ")}.`);
  }
  const unassigned = speakers
    .filter((speaker) => !assignments.has(speaker.key))
    .map((speaker) => speaker.name || speaker.key);
  if (unassigned.length) {
    issues.push(`Assign every discovered speaker to one group. Unassigned: ${unassigned.join(", ")}.`);
  }
  return issues;
}

function createAnalysisProfileDraft(context) {
  const fields = Array.isArray(context?.metadataFields) ? context.metadataFields : [];
  return {
    sortFields: [],
    automaticGroupField: "",
    metadataFilters: Object.fromEntries(
      fields.map((field) => [String(field.name || ""), [...(field.values || [])]]),
    ),
    manualGroups: [],
  };
}

function analysisProfileIssues(context, draft, textEnabled = false) {
  const issues = [];
  if (!context || typeof context.sourceManifest !== "string" || !/^[0-9a-f]{64}$/i.test(context.sourceManifestSha256 || "")) {
    return ["Load source metadata before customizing the output."];
  }
  const fields = new Map((context.metadataFields || []).map((field) => [field.name, field]));
  const sortFields = Array.isArray(draft?.sortFields) ? draft.sortFields : [];
  if (new Set(sortFields).size !== sortFields.length) {
    issues.push("Each metadata sort field can be used only once.");
  }
  sortFields.forEach((field) => {
    if (!fields.has(field)) issues.push(`Unknown metadata sort field: ${field}.`);
  });
  if (draft?.automaticGroupField && !fields.has(draft.automaticGroupField)) {
    issues.push(`Unknown automatic grouping field: ${draft.automaticGroupField}.`);
  }
  const filters = draft?.metadataFilters && typeof draft.metadataFilters === "object"
    ? draft.metadataFilters
    : {};
  Object.entries(filters).forEach(([field, values]) => {
    const available = new Set(fields.get(field)?.values || []);
    if (
      !fields.has(field)
      || !Array.isArray(values)
      || (available.size > 0 && !values.length)
    ) {
      issues.push(`${field || "Metadata"} must keep at least one value visible.`);
      return;
    }
    values.forEach((value) => {
      if (!available.has(value)) issues.push(`Unknown ${field} value: ${value}.`);
    });
  });

  const preview = resolveAnalysisProfilePreview(context, draft);
  const sourceIds = new Set(preview.orderedSourceIds);
  const speakerSources = new Map(
    (context.speakers || []).map((speaker) => [
      speaker.id,
      (speaker.sourceIds || []).filter((sourceId) => sourceIds.has(sourceId)),
    ]),
  );
  const groupIds = new Set();
  const groupNames = new Set();
  const assignments = new Map();
  (draft?.manualGroups || []).forEach((group, groupIndex) => {
    const groupId = String(group.id || "").trim();
    const groupName = String(group.name || "").trim();
    const normalizedName = groupName.toLocaleLowerCase();
    if (!groupId || !groupName) {
      issues.push(`Manual group ${groupIndex + 1} needs an id and name.`);
    } else if (groupIds.has(groupId) || groupNames.has(normalizedName)) {
      issues.push(`Manual group ids and names must be unique; duplicate: ${groupName}.`);
    }
    groupIds.add(groupId);
    groupNames.add(normalizedName);
    if (!Array.isArray(group.members) || !group.members.length) {
      issues.push(`${groupName || `Manual group ${groupIndex + 1}`} needs at least one speaker or source.`);
      return;
    }
    group.members.forEach((member) => {
      let matchedSources = [];
      if (member?.type === "speaker" && (speakerSources.get(member.id) || []).length) {
        matchedSources = speakerSources.get(member.id);
      } else if (member?.type === "source" && sourceIds.has(member.id)) {
        matchedSources = [member.id];
      } else {
        issues.push(`${groupName || `Manual group ${groupIndex + 1}`} contains an unknown ${member?.type || "member"}: ${member?.id || "(blank)"}.`);
        return;
      }
      matchedSources.forEach((sourceId) => {
        if (assignments.has(sourceId)) {
          issues.push(`Source ${sourceId} belongs to more than one manual group or member selection.`);
        } else {
          assignments.set(sourceId, groupId);
        }
      });
    });
  });
  if (!preview.orderedSourceIds.length) {
    issues.push("Metadata filters hide every source.");
  }
  if (textEnabled) {
    const sourceById = new Map((context.sources || []).map((source) => [source.id, source]));
    const groupBySource = new Map();
    preview.groups.forEach((group) => {
      (group.sourceIds || []).forEach((sourceId) => groupBySource.set(sourceId, group.id));
    });
    const groupsBySpeaker = new Map();
    const speakerNames = new Map();
    preview.orderedSourceIds.forEach((sourceId) => {
      const source = sourceById.get(sourceId);
      if (!source) return;
      const speakerId = source.speakerId;
      if (!groupsBySpeaker.has(speakerId)) groupsBySpeaker.set(speakerId, new Set());
      groupsBySpeaker.get(speakerId).add(groupBySource.get(sourceId));
      speakerNames.set(speakerId, source.speaker || speakerId);
    });
    groupsBySpeaker.forEach((groupIds, speakerId) => {
      if (groupIds.size > 1) {
        issues.push(`Text is speaker-level, so every visible source for ${speakerNames.get(speakerId)} must stay in the same output group.`);
      }
    });
  }
  return issues;
}

function resolveAnalysisProfilePreview(context, draft) {
  const fields = new Map((context?.metadataFields || []).map((field) => [field.name, field]));
  const filters = draft?.metadataFilters || {};
  const sourceOrder = new Map((context?.sources || []).map((source, index) => [source.id, index]));
  const visible = (context?.sources || []).filter((source) => Object.entries(filters).every(
    ([field, values]) => !fields.has(field)
      || (values || []).length === (fields.get(field).values || []).length
      || (values || []).includes(String(source.metadata?.[field] || "").trim()),
  ));
  const sortFields = draft?.sortFields || [];
  visible.sort((left, right) => {
    for (const field of sortFields) {
      const leftValue = String(left.metadata?.[field] || "").trim();
      const rightValue = String(right.metadata?.[field] || "").trim();
      if (Boolean(leftValue) !== Boolean(rightValue)) return leftValue ? -1 : 1;
      if (leftValue < rightValue) return -1;
      if (leftValue > rightValue) return 1;
    }
    return sourceOrder.get(left.id) - sourceOrder.get(right.id);
  });
  const orderedSourceIds = visible.map((source) => source.id);
  const visibleIds = new Set(orderedSourceIds);
  const speakers = new Map((context?.speakers || []).map((speaker) => [speaker.id, speaker.sourceIds || []]));
  const assigned = new Set();
  const groups = [];
  (draft?.manualGroups || []).forEach((group) => {
    const memberIds = new Set();
    (group.members || []).forEach((member) => {
      const candidates = member.type === "speaker" ? speakers.get(member.id) || [] : [member.id];
      candidates.forEach((sourceId) => {
        if (visibleIds.has(sourceId)) memberIds.add(sourceId);
      });
    });
    const groupSourceIds = orderedSourceIds.filter((sourceId) => memberIds.has(sourceId));
    groupSourceIds.forEach((sourceId) => assigned.add(sourceId));
    groups.push({ id: group.id, name: group.name, sourceIds: groupSourceIds });
  });
  const remaining = visible.filter((source) => !assigned.has(source.id));
  if (draft?.automaticGroupField) {
    const automatic = new Map();
    remaining.forEach((source) => {
      const name = String(source.metadata?.[draft.automaticGroupField] || "").trim() || "(blank)";
      if (!automatic.has(name)) automatic.set(name, []);
      automatic.get(name).push(source.id);
    });
    automatic.forEach((sourceIdsForGroup, name) => groups.push({ id: `metadata-${name}`, name, sourceIds: sourceIdsForGroup }));
  } else if (remaining.length) {
    groups.push({ id: "ungrouped", name: "All other sources", sourceIds: remaining.map((source) => source.id) });
  }
  return { orderedSourceIds, groups };
}

function buildAnalysisProfilePayload(context, draft) {
  const filters = {};
  const availableByField = new Map(
    (context.metadataFields || []).map((field) => [field.name, field.values || []]),
  );
  Object.entries(draft.metadataFilters || {}).forEach(([field, values]) => {
    if (values.length < (availableByField.get(field) || []).length) filters[field] = [...values];
  });
  return {
    format_version: 1,
    source_manifest: {
      path: context.sourceManifest,
      sha256: context.sourceManifestSha256,
    },
    sort_fields: [...(draft.sortFields || [])],
    automatic_group_field: draft.automaticGroupField || null,
    manual_groups: (draft.manualGroups || []).map((group) => ({
      id: group.id,
      name: String(group.name || "").trim(),
      members: (group.members || []).map((member) => ({ type: member.type, id: member.id })),
    })),
    metadata_filters: filters,
  };
}

function analysisRunGateReasons({
  modalities,
  outputRoot,
  writeCombinedWorkbook,
  discoverySignature,
  currentSignature,
  speakers,
  groups,
  profileContext = null,
  profileDraft = null,
  includeProbabilitySheets = true,
  confidenceLevelText = "95",
  headlinePolicy = "weighted",
  defaultReferenceText,
  referenceOverridesText,
}) {
  const reasons = [];
  if (!modalities.length) {
    reasons.push("Enable Video / iMotions, Audio, or Text.");
  } else {
    modalities.forEach((modality) => {
      if (!String(modality.sourcePath || "").trim()) {
        const labels = { imotions: "Video / iMotions", audio: "Audio", text: "Text" };
        const label = labels[modality.name] || modality.name;
        reasons.push(`Choose a source folder for ${label}.`);
      }
    });
  }
  if (!String(outputRoot || "").trim()) {
    reasons.push("Choose an Analysis output folder.");
  }
  if (!writeCombinedWorkbook) {
    return reasons;
  }
  if (!discoverySignature || discoverySignature !== currentSignature) {
    reasons.push("Load source metadata from the current modality sources in Customize output.");
  }
  if (profileContext) {
    reasons.push(...analysisProfileIssues(
      profileContext,
      profileDraft,
      modalities.some((modality) => modality.name === "text"),
    ));
  } else if (Array.isArray(speakers) && Array.isArray(groups)) {
    if (!speakers.length) {
      reasons.push("Discover at least one speaker for the combined workbook.");
    }
    reasons.push(...analysisSpeakerGroupIssues(speakers, groups));
  } else {
    reasons.push("Load and review source metadata in Customize output.");
  }

  if (!new Set(["weighted", "equal"]).has(String(headlinePolicy || "").trim())) {
    reasons.push("Choose a valid speaker mean method.");
  }
  if (includeProbabilitySheets) {
    const confidenceLevel = Number(String(confidenceLevelText || "").trim());
    if (!Number.isFinite(confidenceLevel) || confidenceLevel < 50 || confidenceLevel >= 100) {
      reasons.push("Confidence level must be at least 50% and below 100%.");
    }
  }

  if (includeProbabilitySheets) {
    const referenceText = String(defaultReferenceText || "").trim();
    if (!referenceText || !Number.isFinite(Number(referenceText))) {
      reasons.push("Default reference must be a finite number.");
    }
    try {
      parseFiniteReferenceOverridesText(referenceOverridesText);
    } catch (error) {
      reasons.push(error.message);
    }
  }
  return reasons;
}

function resolveAnalysisHydration(currentPath, sourcePath, replaceExisting, sourceMethod = "run") {
  const cleanCurrentPath = String(currentPath || "").trim();
  const cleanSourcePath = String(sourcePath || "").trim();
  if (!replaceExisting && (!cleanSourcePath || cleanCurrentPath)) {
    return null;
  }
  return {
    enabled: Boolean(cleanSourcePath),
    sourcePath: cleanSourcePath,
    sourceMethod,
  };
}

function analysisGroupAccessibleLabels(groupName, speakerName = "") {
  const cleanGroupName = String(groupName || "").trim() || "speaker group";
  return {
    remove: `Remove ${cleanGroupName}`,
    assign: speakerName ? `Assign ${speakerName} to ${cleanGroupName}` : "",
  };
}

function chooseAnalysisFocusKey(preferredFocusKey, previousFocusKey, availableFocusKeys) {
  return [preferredFocusKey, previousFocusKey]
    .find((focusKey) => focusKey && availableFocusKeys.includes(focusKey)) || "";
}

function createAnalysisAsyncOperation() {
  return { generation: 0, pending: false, signature: "" };
}

function beginAnalysisAsyncOperation(operation, signature) {
  if (operation.pending) {
    return null;
  }
  operation.generation += 1;
  operation.pending = true;
  operation.signature = signature;
  return { generation: operation.generation, signature };
}

function isAnalysisAsyncOperationCurrent(operation, token, currentSignature) {
  return Boolean(
    token
    && operation.pending
    && operation.generation === token.generation
    && operation.signature === token.signature
    && token.signature === currentSignature,
  );
}

function invalidateAnalysisAsyncOperation(operation) {
  operation.generation += 1;
  operation.pending = false;
  operation.signature = "";
}

function finishAnalysisAsyncOperation(operation, token) {
  if (!token || operation.generation !== token.generation || operation.signature !== token.signature) {
    return false;
  }
  operation.pending = false;
  operation.signature = "";
  return true;
}

function buildAnalysisWorkflowRequest({
  modalities,
  outputRoot,
  writeCombinedWorkbook,
  includeConstructComparison = true,
  includeProbabilitySheets = true,
  confidenceLevel = 0.95,
  headlinePolicy = "weighted",
  defaultReference,
  referenceOverrides,
  speakerGroups,
  analysisProfile = null,
  writeGraphs,
  includeLogscale,
  includeLandmarks,
  includeTiming,
  excludeGeometry,
}) {
  const hasRunModality = modalities.some((modality) => modality.sourceMethod === "run");
  return {
    outputRoot,
    writeCombinedWorkbook,
    includeConstructComparison: writeCombinedWorkbook && includeConstructComparison,
    includeProbabilitySheets: writeCombinedWorkbook && includeProbabilitySheets,
    confidenceLevel,
    headlinePolicy,
    defaultReference,
    referenceOverrides,
    speakerGroups: writeCombinedWorkbook && !analysisProfile ? speakerGroups : [],
    analysisProfile: writeCombinedWorkbook ? analysisProfile : null,
    writeGraphs: hasRunModality && writeGraphs,
    includeLogscale: hasRunModality && includeLogscale,
    includeLandmarks,
    includeTiming,
    excludeGeometry,
    modalities,
  };
}

function analysisFailureMessage(progress) {
  const failedStage = String(progress?.failedStage || "").trim();
  const error = String(progress?.error || progress?.label || "Failed").trim();
  const stagePrefix = failedStage ? `${failedStage} failed` : "";
  const errorIncludesStage = stagePrefix
    && error.toLowerCase().startsWith(`${stagePrefix.toLowerCase()}:`);
  const prefix = stagePrefix && !errorIncludesStage ? `${stagePrefix}: ${error}` : error;
  const completedOutputs = progress?.completedOutputs && typeof progress.completedOutputs === "object"
    ? Object.entries(progress.completedOutputs)
    : [];
  if (!completedOutputs.length) {
    return prefix;
  }
  const completed = completedOutputs
    .map(([modality, path]) => `${modality.charAt(0).toUpperCase()}${modality.slice(1)}: ${path}`)
    .join("; ");
  return `${prefix}. Completed outputs: ${completed}`;
}
// ANALYSIS_UI_LOGIC_END

// CATALOG_UI_LOGIC_START
function isCatalogScan(scan) {
  return Boolean(scan && scan.source_kind === "catalog" && Array.isArray(scan.sources));
}

function catalogSources(scan) {
  return isCatalogScan(scan) ? scan.sources.slice() : [];
}

function catalogMetadataFields(scan) {
  const fields = [];
  const seen = new Set();
  const add = (field) => {
    const label = String(field || "").trim();
    if (label && !seen.has(label)) {
      seen.add(label);
      fields.push(label);
    }
  };
  (Array.isArray(scan?.metadata_headers) ? scan.metadata_headers : []).forEach(add);
  catalogSources(scan).forEach((source) => {
    Object.keys(source.metadata && typeof source.metadata === "object" ? source.metadata : {}).forEach(add);
  });
  return fields;
}

function visibleCatalogSources(sources, options = {}) {
  const filterField = String(options.filterField || "");
  const filterText = String(options.filterText || "").trim().toLocaleLowerCase();
  const sortField = String(options.sortField || "");
  const sortDirection = options.sortDirection === "desc" ? -1 : 1;
  const indexed = (Array.isArray(sources) ? sources : []).map((source, index) => ({ source, index }));
  const visible = filterText
    ? indexed.filter(({ source }) => {
        const metadata = source.metadata && typeof source.metadata === "object" ? source.metadata : {};
        const values = filterField ? [metadata[filterField]] : Object.values(metadata);
        return values.some((value) => String(value || "").toLocaleLowerCase().includes(filterText));
      })
    : indexed;
  if (sortField) {
    visible.sort((left, right) => {
      const leftValue = String(left.source.metadata?.[sortField] || "");
      const rightValue = String(right.source.metadata?.[sortField] || "");
      const compared = leftValue.localeCompare(rightValue, undefined, { numeric: true, sensitivity: "base" });
      return compared ? compared * sortDirection : left.index - right.index;
    });
  }
  return visible.map(({ source }) => source);
}

function setVisibleCatalogSelection(selectedSourceIds, visibleSources, selected) {
  const next = new Set(selectedSourceIds || []);
  (visibleSources || []).forEach((source) => {
    const sourceId = String(source.source_id || source.id || "");
    if (!sourceId) {
      return;
    }
    if (selected) {
      next.add(sourceId);
    } else {
      next.delete(sourceId);
    }
  });
  return next;
}
// CATALOG_UI_LOGIC_END

// Single source of truth for UI-only state. Backend state is still fetched from
// /api/state, but selections like the active speaker and segment list live here.
// The legacy "manual" mode value and DOM ids remain for saved-manifest compatibility;
// all user-facing copy calls this workflow Focus.
const state = {
  module: "home",
  scan: null,
  audioCatalog: null,
  audioCatalogLoadToken: 0,
  mode: "",
  audioMode: "batch",
  analysisSpeakers: [],
  analysisSpeakerGroups: [],
  analysisProfileContext: null,
  analysisProfileDraft: null,
  analysisDiscoverySignature: "",
  analysisDiscoveryOperation: createAnalysisAsyncOperation(),
  analysisSubmissionOperation: createAnalysisAsyncOperation(),
  nextAnalysisGroupId: 1,
  settingsLoaded: false,
  accessLoaded: false,
  termsAccepted: false,
  closing: false,
  pendingRevoke: false,
  workflow: {
    enabled: false,
    active: false,
    plan: null,
    imports: {
      face: "",
      audio: "",
      text: "",
      analysis: "",
    },
  },
  activeRunIds: {
    procurement: null,
    audio: null,
    analysis: null,
  },
  handledRunIds: new Set(),
  pendingAudioOutput: "",
  activeSpeaker: "",
  selectedSpeakers: new Set(),
  selectedSourceIds: new Set(),
  audioSelectedSourceIds: new Set(),
  selectedVideoId: "",
  selectedVideo: null,
  segmentsByVideo: new Map(),
  selectedSegmentId: null,
  nextSegmentId: 1,
  drag: null,
  playerSyncTimer: null,
};

// Small JSON helper shared by all screens. Every API error returns a JSON
// payload, so callers can display the server's message directly in the status.
function api(path, options = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), API_TIMEOUT_MS);
  const init = {
    headers: {
      "Content-Type": "application/json",
      "X-Launcher-Token": launcherToken,
    },
    ...options,
    signal: controller.signal,
  };
  if (init.body && typeof init.body !== "string") {
    init.body = JSON.stringify(init.body);
  }
  return fetch(path, init)
    .then(async (response) => {
      const payload = await response.json();
      if (!response.ok) {
        if (payload.accessRevoked) {
          closeApplication(false);
        }
        throw new Error(payload.error || response.statusText);
      }
      return payload;
    })
    .catch((error) => {
      if (error.name === "AbortError") {
        throw new Error("The local tool did not respond within 15 seconds.");
      }
      throw error;
    })
    .finally(() => window.clearTimeout(timeout));
}

function applySettings(settings = {}) {
  state.settingsLoaded = true;
  youtubeApiKeyInput.value = "";
  huggingFaceTokenInput.value = "";
  clearYoutubeApiKeyToggle.checked = false;
  clearHuggingFaceTokenToggle.checked = false;
  renderCredentialStatus(
    youtubeApiKeyStatus,
    Boolean(settings.youtubeApiKeyConfigured),
    settings.youtubeApiKeyMasked,
  );
  renderCredentialStatus(
    huggingFaceTokenStatus,
    Boolean(settings.huggingFaceTokenConfigured),
    settings.huggingFaceTokenMasked,
  );
  youtubeApiKeyInput.placeholder = settings.youtubeApiKeyConfigured
    ? "Leave blank to keep the configured key"
    : "Paste a new API key";
  huggingFaceTokenInput.placeholder = settings.huggingFaceTokenConfigured
    ? "Leave blank to keep the configured token"
    : "Paste a new token";
  youtubeCookiesBrowserSelect.value = settings.youtubeCookiesBrowser || "";
  resourceLimitsEnabledToggle.checked = settings.resourceLimitsEnabled !== false;
  maxCpuPercentInput.value = String(settings.maxCpuPercent ?? 90);
  maxCpuCoresInput.value = String(settings.maxCpuCores ?? 0);
  maxGpuPercentInput.value = String(settings.maxGpuPercent ?? 95);
  ramLimitModeSelect.value = settings.ramLimitMode || "percent";
  maxRamPercentInput.value = String(settings.maxRamPercent ?? 90);
  maxRamGbInput.value = String(settings.maxRamGb ?? 16);
  nativeThreadsInput.value = String(settings.nativeThreads ?? 1);
  resourcePollSecondsInput.value = String(settings.resourcePollSeconds ?? 2);
  updateRamLimitMode();
  updateResourceLimitState();
  renderResourceCapabilities(settings.resourceCapabilities || {});
  if (settings.settingsWarning) {
    resourceCapabilitiesText.textContent = `Warning: ${settings.settingsWarning} ${resourceCapabilitiesText.textContent}`;
  }
}

function renderCredentialStatus(element, isConfigured, maskedValue) {
  element.classList.toggle("configured", isConfigured);
  element.textContent = isConfigured ? `Configured: ${maskedValue || "********"}` : "Not configured";
}

function updateRamLimitMode() {
  const useGigabytes = ramLimitModeSelect.value === "gb";
  maxRamPercentField.classList.toggle("hidden", useGigabytes);
  maxRamGbField.classList.toggle("hidden", !useGigabytes);
}

function updateResourceLimitState() {
  const disabled = !resourceLimitsEnabledToggle.checked;
  [
    maxCpuPercentInput,
    maxCpuCoresInput,
    maxGpuPercentInput,
    ramLimitModeSelect,
    maxRamPercentInput,
    maxRamGbInput,
    nativeThreadsInput,
    resourcePollSecondsInput,
  ].forEach((input) => {
    input.disabled = disabled;
  });
}

function renderResourceCapabilities(capabilities) {
  const cpuCount = Number(capabilities.logicalCpuCount || 0);
  const totalRamGb = Number(capabilities.totalRamGb || 0);
  const parts = [];
  if (cpuCount) {
    parts.push(`${cpuCount} logical CPUs`);
  }
  if (totalRamGb) {
    parts.push(`${totalRamGb.toFixed(1)} GB RAM`);
  }
  parts.push(capabilities.processMonitoring ? "process monitoring ready" : "install psutil for enforcement");
  parts.push(capabilities.nvidiaGpuTelemetry ? "NVIDIA GPU telemetry ready" : "GPU telemetry unavailable");
  resourceCapabilitiesText.textContent = parts.join(" / ");
}

function applyAccess(access = {}) {
  state.accessLoaded = true;
  state.termsAccepted = Boolean(access.termsAccepted);
  eulaPathInput.value = access.eulaPath || "";
  if (!state.termsAccepted) {
    closeApplication(false);
  }
}

function canUseApp() {
  if (state.accessLoaded && !state.termsAccepted) {
    closeApplication(false);
    return false;
  }
  return true;
}

function recheckAccess() {
  return api("/api/state")
    .then((payload) => {
      if (payload.access) {
        applyAccess(payload.access);
      }
      return canUseApp();
    })
    .catch(() => {
      closeApplication(false);
      return false;
    });
}

async function saveSettings(updates) {
  const payload = await api("/api/settings", { method: "POST", body: updates });
  applySettings(payload.settings || {});
  return payload.settings || {};
}

async function closeApplication(requestServerClose = true) {
  if (state.closing) {
    return;
  }
  state.closing = true;
  if (progressPollTimer !== null) {
    window.clearTimeout(progressPollTimer);
    progressPollTimer = null;
  }
  setStatus("Closing app...");
  if (requestServerClose) {
    try {
      await fetch("/api/close", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Launcher-Token": launcherToken },
        body: "{}",
      });
    } catch (_) {
      // The server may already be shutting down. The UI still blanks itself.
    }
  }
  try {
    if (window.pywebview && window.pywebview.api && window.pywebview.api.close_window) {
      await window.pywebview.api.close_window();
      return;
    }
  } catch (_) {
    // Browser-app fallback has no pywebview bridge.
  }
  document.documentElement.innerHTML = "";
  try {
    window.open("", "_self");
    window.close();
  } catch (_) {
    // Browsers can block script-close; navigating away still shuts the UI.
  }
  window.setTimeout(() => window.location.replace("about:blank"), 50);
}

async function persistSettingsForm() {
  await saveSettings({
    youtubeApiKey: youtubeApiKeyInput.value.trim(),
    huggingFaceToken: huggingFaceTokenInput.value.trim(),
    clearYouTubeApiKey: clearYoutubeApiKeyToggle.checked,
    clearHuggingFaceToken: clearHuggingFaceTokenToggle.checked,
    youtubeCookiesBrowser: youtubeCookiesBrowserSelect.value,
    resourceLimitsEnabled: resourceLimitsEnabledToggle.checked,
    maxCpuPercent: requiredNumber(maxCpuPercentInput, "Maximum CPU load", 10, 100),
    maxCpuCores: requiredNumber(maxCpuCoresInput, "Maximum CPU cores", 0, 256, true),
    maxGpuPercent: requiredNumber(maxGpuPercentInput, "Maximum GPU load", 10, 100),
    ramLimitMode: ramLimitModeSelect.value,
    maxRamPercent: requiredNumber(maxRamPercentInput, "Maximum system RAM", 10, 95),
    maxRamGb: requiredNumber(maxRamGbInput, "Maximum tool RAM", 1, 1024),
    nativeThreads: requiredNumber(nativeThreadsInput, "Native library threads", 1, 256, true),
    resourcePollSeconds: requiredNumber(resourcePollSecondsInput, "Monitor interval", 0.5, 30),
  });
  resetRevokeConfirmation();
  settingsDialog.close();
  setStatus("Settings saved");
}

function requiredNumber(input, label, minimum, maximum, integer = false) {
  const text = String(input.value ?? "").trim();
  if (!text) {
    throw new Error(`${label} is required.`);
  }
  const value = Number(text);
  if (!Number.isFinite(value)) {
    throw new Error(`${label} must be a number.`);
  }
  if (integer && !Number.isInteger(value)) {
    throw new Error(`${label} must be a whole number.`);
  }
  if (value < minimum || value > maximum) {
    throw new Error(`${label} must be between ${minimum} and ${maximum}.`);
  }
  return value;
}

function resetRevokeConfirmation() {
  state.pendingRevoke = false;
  revokeAccessButton.textContent = "Revoke access";
}

async function revokeAccess() {
  if (!state.pendingRevoke) {
    state.pendingRevoke = true;
    revokeAccessButton.textContent = "Confirm revoke and close";
    setStatus("Click again to revoke access and close the app.");
    return;
  }
  const payload = await api("/api/revoke-access", { method: "POST", body: {} });
  applyAccess(payload.access || {});
  await closeApplication(false);
}

// Screen switching is kept separate from access refreshes so callers can decide
// when to await the EULA check and when to only reflect current cached state.
function activateScreen(name) {
  screens.forEach((screen) => screen.classList.toggle("active", screen.dataset.screen === name));
  stepButtons.forEach((button) => button.classList.toggle("active", button.dataset.screenTarget === name));
}

async function showScreen(name) {
  if (await recheckAccess()) {
    activateScreen(name);
  }
}

// Stage navigation controls the app shell: the home screen is separate from the
// module workflow so Procurement, Processing, and Analysis can grow independently.
async function showModeHome() {
  if (!(await recheckAccess())) {
    return;
  }
  state.module = "home";
  modeHome.classList.remove("hidden");
  workflowApp.classList.add("hidden");
}

async function showProcurement() {
  if (!(await recheckAccess())) {
    return;
  }
  state.module = "procurement";
  modeHome.classList.add("hidden");
  workflowApp.classList.remove("hidden");
  moduleTitle.textContent = "Procurement";
  procurementSteps.classList.remove("hidden");
  activateScreen("input");
  setStatus("Ready");
}

async function showProcessingHub() {
  if (!(await recheckAccess())) {
    return;
  }
  state.module = "processing";
  modeHome.classList.add("hidden");
  workflowApp.classList.remove("hidden");
  moduleTitle.textContent = "Processing";
  procurementSteps.classList.add("hidden");
  activateScreen("processing-hub");
  setStatus("Ready");
}

async function showAnalysis() {
  if (!(await recheckAccess())) {
    return;
  }
  state.module = "analysis";
  modeHome.classList.add("hidden");
  workflowApp.classList.remove("hidden");
  moduleTitle.textContent = "Analysis";
  procurementSteps.classList.add("hidden");
  activateScreen("analysis-input");
  hydrateAnalysisModalitiesFromImports();
  updateAnalysisForm();
  setStatus("Ready");
}

function setRunStepEnabled(isEnabled) {
  const runStep = stepButtons.find((button) => button.dataset.screenTarget === "run");
  if (runStep) {
    runStep.disabled = !isEnabled;
  }
}

function setStatus(message) {
  statusLabel.textContent = message;
  if (homeStatusLabel) {
    homeStatusLabel.textContent = message;
  }
}

function setBusy(isBusy) {
  scanButton.disabled = isBusy;
  rescanButton.disabled = isBusy;
  runButton.disabled = isBusy || !state.mode;
  toRunButton.disabled = isBusy || !state.mode;
}

function updateWorkflowPlanner() {
  state.workflow.enabled = guidedWorkflowToggle.checked;
  if (!state.workflow.enabled) {
    state.workflow.active = false;
    state.workflow.plan = null;
  }
  workflowPlannerBody.classList.toggle("hidden", !state.workflow.enabled);
}

function selectedWorkflowProcesses() {
  return [
    { key: "face", enabled: workflowFaceToggle.checked, method: workflowFaceMethod.value, input: workflowFaceImportPath },
    { key: "audio", enabled: workflowAudioToggle.checked, method: workflowAudioMethod.value, input: workflowAudioImportPath },
    { key: "text", enabled: workflowTextToggle.checked, method: workflowTextMethod.value, input: workflowTextImportPath },
  ].filter((item) => item.enabled);
}

function syncWorkflowImportsToProcessingHub() {
  const processingEnabled = workflowProcessingToggle.checked;
  const faceEnabled = processingEnabled && workflowFaceToggle.checked;
  const audioEnabled = processingEnabled && workflowAudioToggle.checked;
  const textEnabled = processingEnabled && workflowTextToggle.checked;
  if (faceEnabled) {
    faceImportPathInput.value = workflowFaceImportPath.value.trim();
  }
  if (audioEnabled) {
    audioImportHubPathInput.value = workflowAudioImportPath.value.trim();
  }
  if (textEnabled) {
    textImportPathInput.value = workflowTextImportPath.value.trim();
  }
  faceImportToggle.checked = faceEnabled && workflowFaceMethod.value === "import" && Boolean(faceImportPathInput.value);
  audioImportHubToggle.checked = audioEnabled && workflowAudioMethod.value === "import" && Boolean(audioImportHubPathInput.value);
  textImportToggle.checked = textEnabled && workflowTextMethod.value === "import" && Boolean(textImportPathInput.value);
}

async function validateUiPath(path, kind, label) {
  const payload = await api("/api/validate-path", {
    method: "POST",
    body: { path, kind },
  });
  if (!payload.valid || !payload.path) {
    throw new Error(`${label} could not be validated.`);
  }
  return payload.path;
}

function currentWorkflowPlan() {
  const processes = workflowProcessingToggle.checked
    ? selectedWorkflowProcesses().map((item) => ({
        key: item.key,
        method: item.method,
        path: item.input.value.trim(),
      }))
    : [];
  return {
    procurement: workflowProcurementToggle.checked,
    processing: workflowProcessingToggle.checked,
    analysis: workflowAnalysisToggle.checked,
    processes,
    audioRun: processes.some((item) => item.key === "audio" && item.method === "run"),
  };
}

async function validateWorkflowImports(plan) {
  for (const process of plan.processes) {
    if (process.method !== "import") {
      continue;
    }
    if (!process.path) {
      throw new Error(`Add an import folder for ${process.key}.`);
    }
    const validated = await validateUiPath(process.path, "folder", `${process.key} import`);
    process.path = validated;
    state.workflow.imports[process.key] = validated;
    const inputByKey = {
      face: workflowFaceImportPath,
      audio: workflowAudioImportPath,
      text: workflowTextImportPath,
    };
    inputByKey[process.key].value = validated;
  }
}

async function startGuidedWorkflow() {
  updateWorkflowPlanner();
  const plan = currentWorkflowPlan();
  if (!plan.procurement && !plan.processing && !plan.analysis) {
    setStatus("Choose at least one workflow stage.");
    return;
  }
  if (plan.processing && !plan.processes.length) {
    setStatus("Choose at least one Processing stream.");
    return;
  }
  try {
    await validateWorkflowImports(plan);
  } catch (error) {
    setStatus(error.message);
    return;
  }
  resetAnalysisForNewWorkflow();
  state.workflow.imports = { face: "", audio: "", text: "", analysis: "" };
  plan.processes.forEach((process) => {
    if (process.method === "import") {
      state.workflow.imports[process.key] = process.path;
    }
  });
  state.workflow.plan = plan;
  state.workflow.active = true;
  syncWorkflowImportsToProcessingHub();
  if (plan.procurement) {
    await showProcurement();
    setStatus("Workflow: start with procurement");
    return;
  }
  await advanceGuidedWorkflow("start");
}

async function advanceGuidedWorkflow(completedStage) {
  const plan = state.workflow.plan;
  if (!state.workflow.active || !plan) {
    return;
  }
  if (completedStage !== "processing" && plan.processing && plan.audioRun) {
    await showProcessingHub();
    await showScreen("audio-input");
    updateAudioMode();
    setStatus("Workflow: run audio processing");
    return;
  }
  if (plan.analysis) {
    await showAnalysis();
    setStatus("Workflow: continue to analysis");
    return;
  }
  state.workflow.active = false;
  await showModeHome();
  setStatus("Workflow complete");
}

async function continueAfterProcurement() {
  if (state.workflow.active) {
    await advanceGuidedWorkflow("procurement");
    return;
  }
  await showProcessingHub();
}

async function continueAfterAudio() {
  if (state.workflow.active) {
    await advanceGuidedWorkflow("processing");
    return;
  }
  showAudioAnalysis();
}

function hydrateAnalysisModalitiesFromImports() {
  const completedAudioPath = state.pendingAudioOutput
    || (state.workflow.active && state.workflow.plan?.audioRun ? audioOutputRootInput.value.trim() : "");
  const facePath = faceImportToggle.checked
    ? faceImportPathInput.value.trim()
    : workflowProcessingToggle.checked && workflowFaceToggle.checked && workflowFaceMethod.value === "import"
      ? workflowFaceImportPath.value.trim()
      : "";
  const audioPath = audioImportHubToggle.checked
    ? audioImportHubPathInput.value.trim()
    : workflowProcessingToggle.checked && workflowAudioToggle.checked && workflowAudioMethod.value === "import"
      ? workflowAudioImportPath.value.trim()
      : state.workflow.imports.audio || completedAudioPath;
  const textPath = textImportToggle.checked
    ? textImportPathInput.value.trim()
    : workflowProcessingToggle.checked && workflowTextToggle.checked && workflowTextMethod.value === "import"
      ? workflowTextImportPath.value.trim()
      : "";
  const replaceExisting = Boolean(state.workflow.active && state.workflow.plan?.analysis);
  hydrateAnalysisModality(analysisImotionsControls, facePath, replaceExisting);
  hydrateAnalysisModality(analysisAudioControls, audioPath, replaceExisting);
  hydrateAnalysisModality(analysisTextControls, textPath, replaceExisting, "import");
}

function hydrateAnalysisModality(controls, sourcePath, replaceExisting, sourceMethod = "run") {
  const hydration = resolveAnalysisHydration(
    controls.source.value,
    sourcePath,
    replaceExisting,
    sourceMethod,
  );
  if (!hydration) {
    return;
  }
  controls.enabled.checked = hydration.enabled;
  controls.source.value = hydration.sourcePath;
  setAnalysisSourceMethod(controls, hydration.sourceMethod);
}

function resetAnalysisForNewWorkflow() {
  analysisImplementedControls.forEach((controls) => {
    controls.enabled.checked = false;
    controls.source.value = "";
    setAnalysisSourceMethod(controls, controls.name === "text" ? "import" : "run");
  });
  state.analysisSpeakers = [];
  state.analysisSpeakerGroups = [];
  state.analysisProfileContext = null;
  state.analysisProfileDraft = null;
  state.analysisDiscoverySignature = "";
  analysisSourceManifestInput.value = "";
  state.nextAnalysisGroupId = 1;
  state.pendingAudioOutput = "";
  invalidateAnalysisAsyncOperation(state.analysisDiscoveryOperation);
  invalidateAnalysisAsyncOperation(state.analysisSubmissionOperation);
  analysisSpeakerDiscoveryStatus.textContent = "Choose source folders, then discover speakers.";
  renderAnalysisCustomization();
}

function showAudioAnalysis() {
  const audioPath =
    state.workflow.imports.audio ||
    audioImportHubPathInput.value.trim() ||
    workflowAudioImportPath.value.trim() ||
    audioOutputRootInput.value.trim();
  if (audioPath) {
    analysisAudioEnabled.checked = true;
    analysisAudioSourcePath.value = audioPath;
    setAnalysisSourceMethod(analysisAudioControls, "run");
  }
  showAnalysis();
}

function getSelectedMode() {
  const checked = modeInputs.find((input) => input.checked);
  return checked ? checked.value : "";
}

function getSelectedBetaOutputMode() {
  const checked = betaOutputModeInputs.find((input) => input.checked);
  return checked ? checked.value : "clean";
}

function resetProcurementMode() {
  modeInputs.forEach((input) => {
    input.checked = false;
  });
  state.mode = "";
  updateMode();
}

// Procurement mode is disabled until the user explicitly chooses a run type.
// This keeps the Run step honest when a scan has completed but no mode is set.
function updateMode() {
  state.mode = getSelectedMode();
  document.querySelectorAll("[data-mode-option]").forEach((option) => {
    option.classList.toggle("active", option.dataset.modeOption === state.mode);
  });
  standardSettings.classList.toggle("hidden", state.mode !== "standard");
  focusSettings.classList.toggle("hidden", state.mode !== "manual");
  cleanSpeakerSettings.classList.toggle("hidden", state.mode !== "clean-speaker-beta");
  updateBetaOutputMode();
  const hasMode = Boolean(state.mode);
  const hasSpeakers = getSelectedSpeakers().length > 0;
  const canRun = hasMode && hasSpeakers;
  runButton.disabled = !canRun;
  toRunButton.disabled = !canRun;
  runButton.textContent = !hasMode
    ? "Select a mode to continue"
    : hasSpeakers
      ? "Start selected mode"
      : "Select at least one speaker";
}

function updateBetaOutputMode() {
  const isPercentage = state.mode === "clean-speaker-beta" && getSelectedBetaOutputMode() === "percentage";
  betaPercentageSettings.classList.toggle("hidden", !isPercentage);
  betaMaxSegmentSettings.classList.toggle("hidden", !isPercentage);
}

function plural(count, singular, pluralValue = `${singular}s`) {
  return `${count} ${count === 1 ? singular : pluralValue}`;
}

function secondsToClock(value) {
  if (!Number.isFinite(value)) {
    return "Unknown";
  }
  const safe = Math.max(0, Math.round(value));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = safe % 60;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
  }
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function secondsToExtractorClock(value) {
  const safe = Math.max(0, Math.round(value));
  const hours = Math.floor(safe / 3600);
  const minutes = Math.floor((safe % 3600) / 60);
  const seconds = safe % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
}

function parseEditableTimecode(value) {
  const text = String(value ?? "").trim().replace(",", ".");
  if (!text) {
    return Number.NaN;
  }
  const parts = text.split(":");
  if (parts.length > 3 || parts.some((part) => !/^\d+(?:\.\d+)?$/.test(part))) {
    return Number.NaN;
  }
  const values = parts.map(Number);
  if (values.some((part) => !Number.isFinite(part) || part < 0)) {
    return Number.NaN;
  }
  if (parts.length === 1) {
    return values[0];
  }
  const seconds = values[values.length - 1];
  const minutes = values[values.length - 2];
  if (seconds >= 60 || (parts.length === 3 && minutes >= 60)) {
    return Number.NaN;
  }
  const hours = parts.length === 3 ? values[0] : 0;
  return hours * 3600 + minutes * 60 + seconds;
}

function formatEditableTimecode(value) {
  const totalTenths = Math.max(0, Math.round(Number(value || 0) * 10));
  const hours = Math.floor(totalTenths / 36000);
  const minutes = Math.floor((totalTenths % 36000) / 600);
  const secondTenths = totalTenths % 600;
  const seconds = Math.floor(secondTenths / 10);
  const fraction = secondTenths % 10;
  const secondsText = `${String(seconds).padStart(2, "0")}${fraction ? `.${fraction}` : ""}`;
  if (hours > 0) {
    return `${hours}:${String(minutes).padStart(2, "0")}:${secondsText}`;
  }
  return `${minutes}:${secondsText}`;
}

function normaliseUploadDate(value) {
  if (!value) {
    return "Upload date unknown";
  }
  const compact = /^(\d{4})(\d{2})(\d{2})$/.exec(value);
  if (compact) {
    return `${compact[1]}-${compact[2]}-${compact[3]}`;
  }
  return value;
}

function parseDateSort(value) {
  if (!value) {
    return 0;
  }
  const compact = /^(\d{4})(\d{2})(\d{2})$/.exec(value);
  if (compact) {
    return Date.parse(`${compact[1]}-${compact[2]}-${compact[3]}`) || 0;
  }
  return Date.parse(value) || 0;
}

function getVideoDuration(video) {
  const metadataDuration = Number(video.duration_seconds);
  if (Number.isFinite(metadataDuration) && metadataDuration > 0) {
    return metadataDuration;
  }
  if (video === state.selectedVideo && Number.isFinite(manualPlayer.duration) && manualPlayer.duration > 0) {
    return manualPlayer.duration;
  }
  return 0;
}

function getAllVideos() {
  if (!state.scan) {
    return [];
  }
  if (isCatalogScan(state.scan)) {
    return catalogSources(state.scan);
  }
  return state.scan.groups.flatMap((group) => group.videos.map((video) => ({ ...video, speaker: group.speaker })));
}

function getSelectedSpeakers() {
  if (!state.scan) {
    return [];
  }
  if (isCatalogScan(state.scan)) {
    return Array.from(new Set(getSelectedVideos().map((video) => video.speaker)));
  }
  return state.scan.groups
    .map((group) => group.speaker)
    .filter((speaker) => state.selectedSpeakers.has(speaker));
}

function getSelectedVideos() {
  if (isCatalogScan(state.scan)) {
    return getAllVideos().filter((video) => state.selectedSourceIds.has(String(video.source_id || video.id || "")));
  }
  const selected = state.selectedSpeakers;
  return getAllVideos().filter((video) => selected.has(video.speaker));
}

function getSelectedSourceIds() {
  return isCatalogScan(state.scan) ? Array.from(state.selectedSourceIds) : [];
}

function getVisibleCatalogVideos() {
  if (!isCatalogScan(state.scan)) {
    return [];
  }
  const active = catalogSources(state.scan).filter((video) => video.speaker === state.activeSpeaker);
  return visibleCatalogSources(active, {
    filterField: catalogFilterField.value,
    filterText: catalogFilterText.value,
    sortField: catalogSortField.value,
    sortDirection: catalogSortDirection.value,
  });
}

function setAllSpeakersSelected(selected) {
  if (isCatalogScan(state.scan)) {
    state.selectedSourceIds = setVisibleCatalogSelection(
      state.selectedSourceIds,
      getVisibleCatalogVideos(),
      selected,
    );
    renderReview();
    updateMode();
    return;
  }
  state.selectedSpeakers.clear();
  if (selected && state.scan) {
    state.scan.groups.forEach((group) => state.selectedSpeakers.add(group.speaker));
  }
  renderReview();
  updateMode();
}

function getActiveGroup() {
  if (!state.scan || !state.scan.groups.length) {
    return null;
  }
  return state.scan.groups.find((group) => group.speaker === state.activeSpeaker) || state.scan.groups[0];
}

function sortVideos(videos) {
  if (isCatalogScan(state.scan)) {
    return videos;
  }
  const sorted = [...videos];
  if (sortSelect.value === "date-desc") {
    sorted.sort((a, b) => parseDateSort(b.upload_date) - parseDateSort(a.upload_date));
  } else if (sortSelect.value === "date-asc") {
    sorted.sort((a, b) => parseDateSort(a.upload_date) - parseDateSort(b.upload_date));
  } else if (sortSelect.value === "length-desc") {
    sorted.sort((a, b) => getVideoDuration(b) - getVideoDuration(a));
  } else if (sortSelect.value === "length-asc") {
    sorted.sort((a, b) => getVideoDuration(a) - getVideoDuration(b));
  }
  return sorted;
}

function initials(value) {
  return String(value || "Video")
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0].toUpperCase())
    .join("");
}

function configureCatalogMetadataControls() {
  const catalog = isCatalogScan(state.scan);
  catalogMetadataControls.classList.toggle("hidden", !catalog);
  sortSelect.closest("label")?.classList.toggle("hidden", catalog);
  toggleAllSpeakersButton.classList.toggle("hidden", catalog);
  if (!catalog) {
    return;
  }
  const fields = catalogMetadataFields(state.scan);
  const previousFilter = catalogFilterField.value;
  const previousSort = catalogSortField.value;
  catalogFilterField.replaceChildren(new Option("All metadata", ""));
  catalogSortField.replaceChildren(new Option("Catalog order", ""));
  fields.forEach((field) => {
    catalogFilterField.appendChild(new Option(field, field));
    catalogSortField.appendChild(new Option(field, field));
  });
  catalogFilterField.value = fields.includes(previousFilter) ? previousFilter : "";
  catalogSortField.value = fields.includes(previousSort) ? previousSort : "";
}

function renderScanTabs() {
  scanTabList.innerHTML = "";
  if (!state.scan) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No scan yet";
    scanTabList.appendChild(empty);
    return;
  }
  state.scan.groups.forEach((group) => {
    const tab = document.createElement("div");
    tab.className = "scan-tab";
    tab.classList.toggle("active", group.speaker === state.activeSpeaker);
    const groupSourceIds = group.videos.map((video) => String(video.source_id || video.id || "")).filter(Boolean);
    const selectedInGroup = isCatalogScan(state.scan)
      ? groupSourceIds.filter((sourceId) => state.selectedSourceIds.has(sourceId)).length
      : 0;
    const groupSelected = isCatalogScan(state.scan)
      ? groupSourceIds.length > 0 && selectedInGroup === groupSourceIds.length
      : state.selectedSpeakers.has(group.speaker);
    tab.classList.toggle("excluded", !groupSelected && selectedInGroup === 0);

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = groupSelected;
    checkbox.indeterminate = isCatalogScan(state.scan) && selectedInGroup > 0 && !groupSelected;
    checkbox.setAttribute("aria-label", `Include ${group.speaker} in this run`);
    checkbox.addEventListener("change", () => {
      if (isCatalogScan(state.scan)) {
        state.selectedSourceIds = setVisibleCatalogSelection(
          state.selectedSourceIds,
          group.videos,
          checkbox.checked,
        );
      } else if (checkbox.checked) {
        state.selectedSpeakers.add(group.speaker);
      } else {
        state.selectedSpeakers.delete(group.speaker);
      }
      renderReview();
      updateMode();
    });

    const button = document.createElement("button");
    button.type = "button";
    button.className = "scan-tab-main";
    button.innerHTML = `<strong>${escapeHtml(group.speaker)}</strong><span>${plural(group.videos.length, "video")}</span>`;
    button.addEventListener("click", () => {
      state.activeSpeaker = group.speaker;
      renderReview();
    });
    tab.append(checkbox, button);
    scanTabList.appendChild(tab);
  });
}

function renderReview() {
  configureCatalogMetadataControls();
  renderScanTabs();
  videoGroups.innerHTML = "";
  if (!state.scan) {
    scanSummary.textContent = "No source scanned yet";
    speakerSelectionSummary.textContent = "No speakers selected";
    toggleAllSpeakersButton.textContent = "Select all";
    toggleAllSpeakersButton.disabled = true;
    speakerTitle.textContent = "Select a source to scan";
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Choose a source and scan it to review videos before procurement.";
    videoGroups.appendChild(empty);
    return;
  }

  const groups = state.scan.groups;
  const count = groups.reduce((total, group) => total + group.videos.length, 0);
  const selectedGroups = getSelectedSpeakers();
  const selectedVideos = getSelectedVideos();
  scanSummary.textContent = `${plural(count, "video")} across ${plural(groups.length, "speaker group")} / ${plural(selectedVideos.length, "video")} selected`;
  speakerSelectionSummary.textContent = `${plural(selectedGroups.length, "speaker")} selected`;
  toggleAllSpeakersButton.textContent = selectedGroups.length === groups.length ? "Clear" : "Select all";
  toggleAllSpeakersButton.disabled = groups.length === 0;
  const group = getActiveGroup();
  if (!group) {
    return;
  }
  speakerTitle.textContent = group.speaker;
  const visibleVideos = isCatalogScan(state.scan) ? getVisibleCatalogVideos() : sortVideos(group.videos);
  if (isCatalogScan(state.scan) && !visibleVideos.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No sources in this speaker group match the metadata filter.";
    videoGroups.appendChild(empty);
  } else {
    videoGroups.appendChild(renderSpeakerGroup(group, visibleVideos, false));
  }
  renderManualList();
}

// The same video row renderer is used for review and Focus selection. The
// title becomes a YouTube link in review and a segment-picker button in Focus.
function renderSpeakerGroup(group, videos, manualList) {
  const wrapper = document.createElement("section");
  wrapper.className = "speaker-group";
  const totalSeconds = videos.reduce((total, video) => total + getVideoDuration(video), 0);
  const head = document.createElement("div");
  head.className = "speaker-head";
  head.innerHTML = `<strong>${escapeHtml(group.speaker)}</strong><span class="speaker-sub">${plural(videos.length, "video")} / ${secondsToClock(totalSeconds)}</span>`;
  wrapper.appendChild(head);
  videos.forEach((video) => wrapper.appendChild(renderVideoRow({ ...video, speaker: group.speaker }, manualList)));
  return wrapper;
}

function renderVideoRow(video, manualList) {
  const row = document.createElement("article");
  row.className = "video-row";
  const catalogRow = isCatalogScan(state.scan);
  row.classList.toggle("catalog-row", catalogRow && !manualList);
  row.classList.toggle("selected", video.id === state.selectedVideoId);
  if (catalogRow && !manualList) {
    const sourceId = String(video.source_id || video.id || "");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.className = "catalog-source-checkbox";
    checkbox.checked = state.selectedSourceIds.has(sourceId);
    checkbox.setAttribute("aria-label", `Include ${sourceId} in this run`);
    checkbox.addEventListener("change", () => {
      state.selectedSourceIds = setVisibleCatalogSelection(
        state.selectedSourceIds,
        [video],
        checkbox.checked,
      );
      renderReview();
      updateMode();
    });
    row.appendChild(checkbox);
  }
  row.append(renderThumbnail(video));

  const main = document.createElement("div");
  main.className = "video-main";
  main.append(renderTitle(video, manualList));
  const meta = document.createElement("div");
  meta.className = "video-meta";
  meta.append(
    createMetaSpan(`Speaker: ${video.speaker}`),
    createMetaSpan(video.duration_display || secondsToClock(video.duration_seconds)),
    createMetaSpan(normaliseUploadDate(video.upload_date)),
    createLicensePill(video.license || "Unknown"),
  );
  if (video.youtube_language) {
    meta.append(createMetaSpan(`YouTube language: ${video.youtube_language}`));
  }
  if (catalogRow && video.metadata && typeof video.metadata === "object") {
    Object.entries(video.metadata).forEach(([label, value]) => {
      if (String(value || "").trim()) {
        meta.append(createMetaSpan(`${label}: ${value}`));
      }
    });
  }
  main.appendChild(meta);

  const side = document.createElement("div");
  if (manualList) {
    side.className = "segment-count";
    side.textContent = plural(getSegments(video.id).length, "segment");
  } else {
    side.className = "speaker-sub";
    side.textContent = catalogRow
      ? String(video.source_id || video.id || "Source")
      : video.youtube_url
        ? "YouTube link"
        : video.source_kind === "docx"
          ? "YouTube source"
          : "Local file";
  }
  row.append(main, side);
  return row;
}

function renderThumbnail(video) {
  const content = document.createElement(video.youtube_url ? "a" : "div");
  content.className = video.youtube_url ? "thumb-link" : "thumb-fallback";
  if (video.youtube_url) {
    content.href = video.youtube_url;
    content.target = "_blank";
    content.rel = "noreferrer";
  }
  if (video.thumbnail_url) {
    const image = document.createElement("img");
    image.src = video.thumbnail_url;
    image.alt = "";
    image.addEventListener("error", () => {
      image.remove();
      content.textContent = initials(video.title || video.speaker);
      content.appendChild(renderDurationBadge(video));
    });
    content.appendChild(image);
  } else {
    content.textContent = initials(video.title || video.speaker);
  }
  content.appendChild(renderDurationBadge(video));
  return content;
}

function renderDurationBadge(video) {
  const duration = document.createElement("span");
  duration.className = "duration-badge";
  duration.textContent = video.duration_display || secondsToClock(video.duration_seconds);
  return duration;
}

function renderTitle(video, manualList) {
  if (manualList) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "video-title-button";
    button.textContent = video.title || video.video_id || "Untitled video";
    button.addEventListener("click", () => openSegmentDialog(video));
    return button;
  }
  if (video.youtube_url) {
    const link = document.createElement("a");
    link.className = "video-title-link";
    link.href = video.youtube_url;
    link.target = "_blank";
    link.rel = "noreferrer";
    link.textContent = video.title || video.video_id || "Untitled video";
    return link;
  }
  const title = document.createElement("span");
  title.className = "video-title-link";
  title.textContent = video.title || "Untitled video";
  return title;
}

function createMetaSpan(text) {
  const span = document.createElement("span");
  span.textContent = text;
  return span;
}

function createLicensePill(text) {
  const span = document.createElement("span");
  span.className = "license-pill";
  span.textContent = text || "Unknown";
  return span;
}

function renderManualList() {
  manualVideoList.innerHTML = "";
  const videos = getSelectedVideos();
  const segmentCount = getSelectedSegmentCount();
  manualSummary.textContent = `${plural(segmentCount, "segment")} selected across ${plural(videos.length, "video")}`;
  manualRunButton.disabled = segmentCount === 0;
  if (!videos.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "Scan videos first, then return here to choose Focus segments.";
    manualVideoList.appendChild(empty);
    return;
  }
  const groups = new Map();
  videos.forEach((video) => {
    if (!groups.has(video.speaker)) {
      groups.set(video.speaker, []);
    }
    groups.get(video.speaker).push(video);
  });
  groups.forEach((items, speaker) => {
    manualVideoList.appendChild(renderSpeakerGroup({ speaker, videos: items }, items, true));
  });
}

function getSegments(videoId) {
  if (!state.segmentsByVideo.has(videoId)) {
    state.segmentsByVideo.set(videoId, []);
  }
  return state.segmentsByVideo.get(videoId);
}

function setSegments(videoId, segments) {
  const normalized = segments
    .map((segment) => ({
      ...segment,
      id: segment.id || `focus-${state.nextSegmentId++}`,
    }))
    .sort((a, b) => a.start - b.start || a.end - b.end);
  state.segmentsByVideo.set(videoId, normalized);
  if (
    videoId === state.selectedVideoId
    && state.selectedSegmentId
    && !normalized.some((segment) => segment.id === state.selectedSegmentId)
  ) {
    state.selectedSegmentId = null;
  }
}

function getSelectedSegmentCount() {
  return getSelectedVideos().reduce((count, video) => count + getSegments(video.id).length, 0);
}

async function browse(kind) {
  await browseInto(kind, kind === "output" ? outputRootInput : sourcePathInput);
}

async function browseInto(kind, input) {
  setStatus("Opening picker...");
  const nativeBrowse = window.pywebview?.api?.browse_for_path;
  const payload = typeof nativeBrowse === "function"
    ? await nativeBrowse(kind)
    : await api("/api/browse", { method: "POST", body: { kind } });
  let selectedPath = "";
  if (!payload.cancelled && payload.path) {
    selectedPath = String(payload.path).trim();
    input.value = selectedPath;
    if (input === sourcePathInput) {
      invalidateProcurementScan();
    }
  }
  setStatus("Ready");
  return selectedPath;
}

function openProcurementSourcePicker() {
  if (!sourcePickerDialog.open) {
    sourcePickerDialog.showModal();
  }
  setStatus("Choose a source type.");
}

async function chooseProcurementSource(kind) {
  sourcePickerDialog.close();
  const selectedPath = await browseInto(kind, sourcePathInput);
  if (selectedPath) {
    await scan();
  }
}

function invalidateProcurementScan() {
  state.scan = null;
  state.activeSpeaker = "";
  state.selectedSpeakers.clear();
  state.selectedSourceIds.clear();
  catalogFilterField.value = "";
  catalogFilterText.value = "";
  catalogSortField.value = "";
  catalogSortDirection.value = "asc";
  state.selectedVideo = null;
  state.selectedVideoId = "";
  state.selectedSegmentId = null;
  state.segmentsByVideo.clear();
  resetProcurementMode();
  renderReview();
}

// Scanning is read-only: it gathers metadata and groups videos before any
// downloading, sampling, or audio processing can begin.
async function scan() {
  const path = sourcePathInput.value.trim();
  if (!path) {
    openProcurementSourcePicker();
    return;
  }
  setBusy(true);
  setStatus("Scanning...");
  try {
    const result = await api("/api/scan", { method: "POST", body: { path } });
    state.scan = result;
    state.activeSpeaker = result.groups[0] ? result.groups[0].speaker : "";
    state.selectedSpeakers = new Set(result.groups.map((group) => group.speaker));
    state.selectedSourceIds = new Set(
      isCatalogScan(result)
        ? catalogSources(result).map((video) => String(video.source_id || video.id || "")).filter(Boolean)
        : [],
    );
    state.selectedVideo = null;
    state.selectedVideoId = "";
    state.selectedSegmentId = null;
    state.segmentsByVideo.clear();
    resetProcurementMode();
    renderReview();
    showScreen("review");
    setStatus("Scan complete");
  } catch (error) {
    setStatus(error.message);
  } finally {
    setBusy(false);
  }
}

// Focus first opens the selection UI. Standard and full modes can start
// immediately because their options are already captured on the review screen.
async function startSelectedMode() {
  updateMode();
  if (!state.mode) {
    setStatus("Select a procurement mode first.");
    return;
  }
  if (!getSelectedSpeakers().length) {
    setStatus("Select at least one speaker before continuing.");
    return;
  }
  setRunStepEnabled(true);
  if (state.mode === "manual") {
    renderManualList();
    showManualRunView();
    showScreen("run");
    return;
  }
  await runProcurement(null);
}

function showRunProgressView() {
  runProgressView.classList.remove("hidden");
  manualRunView.classList.add("hidden");
}

function showManualRunView() {
  runProgressView.classList.add("hidden");
  manualRunView.classList.remove("hidden");
}

async function runProcurement(segmentManifest) {
  if (!sourcePathInput.value.trim()) {
    setStatus("Choose a source before running.");
    showScreen("input");
    return;
  }
  if (!state.scan) {
    setStatus("Scan the current source before running procurement.");
    showScreen("input");
    return;
  }
  const mode = getSelectedMode();
  if (!mode) {
    setStatus("Select a procurement mode first.");
    showScreen("review");
    return;
  }
  if (!getSelectedSpeakers().length) {
    setStatus("Select at least one speaker before running.");
    showScreen("review");
    return;
  }
  const manifest = segmentManifest || (mode === "manual" ? createSegmentManifest() : null);
  if (mode === "manual" && (!manifest || !manifest.selected_segments.length)) {
    setStatus("Focus mode needs at least one selected segment.");
    showManualRunView();
    showScreen("run");
    return;
  }
  setRunStepEnabled(true);
  showRunProgressView();
  procurementNextStep.classList.add("hidden");
  showScreen("run");
  runTitle.textContent =
    mode === "full"
      ? "Downloading full videos"
      : mode === "manual"
        ? "Creating focused videos"
        : mode === "clean-speaker-beta"
          ? "Finding clean speaker segments"
          : "Sampling videos";
  runSubtitle.textContent = "The selected procurement run is in progress.";
  progressBar.style.width = "0%";
  progressLabel.textContent = "Starting...";
  setStatus("Running");
  const isCleanSpeakerBeta = mode === "clean-speaker-beta";
  const betaOutputMode = getSelectedBetaOutputMode();
  const betaUsesPercentage = isCleanSpeakerBeta && betaOutputMode === "percentage";
  try {
    const response = await api("/api/run", {
      method: "POST",
      body: {
        mode,
        sourcePath: sourcePathInput.value.trim(),
        outputRoot: outputRootInput.value.trim(),
        maxSegmentSeconds:
          betaUsesPercentage
            ? requiredNumber(betaMaxSegmentInput, "Maximum clean clip length", 1, 3600)
            : mode === "standard"
              ? selectedMaxSegmentSeconds()
              : 30,
        percentage:
          betaUsesPercentage
            ? requiredNumber(betaPercentInput, "Target percentage", 0.01, 100) / 100
            : isCleanSpeakerBeta
              ? 0.10
              : requiredNumber(samplePercentInput, "Sample percentage", 0.01, 100) / 100,
        segmentManifest: manifest,
        selectedSpeakers: getSelectedSpeakers(),
        selectedSourceIds: getSelectedSourceIds(),
        catalogSha256: isCatalogScan(state.scan) ? String(state.scan.catalog_sha256 || "") : "",
        videoCount: betaRunVideoCount(mode),
        betaOutputMode,
        betaMinCleanSeconds: isCleanSpeakerBeta
          ? requiredNumber(betaMinCleanInput, "Minimum clean overlap", 0.01, 86400)
          : 10,
        betaGapSeconds: isCleanSpeakerBeta
          ? requiredNumber(betaGapInput, "Black/silent gap", 0, 60)
          : 0,
        betaIdentityStills: isCleanSpeakerBeta
          ? requiredNumber(betaIdentityStillsInput, "Identity still count", 1, 200, true)
          : 20,
        betaScanFps: isCleanSpeakerBeta ? requiredNumber(betaScanFpsInput, "Scan FPS", 0.1, 10) : 1,
        betaValidationFps: isCleanSpeakerBeta
          ? requiredNumber(betaValidationFpsInput, "Validation FPS", 0.1, 10)
          : 4,
        betaMaxDownloadHeight: isCleanSpeakerBeta
          ? requiredNumber(betaMaxDownloadHeightInput, "Maximum download height", 0, 4320, true)
          : 720,
        betaOnlyVideoIds: betaOnlyVideoIdList(),
        betaRandomOne: betaRandomOneToggle.checked,
        betaRandomSeed: betaRandomSeedInput.value.trim(),
        betaFaceConfidence: isCleanSpeakerBeta
          ? requiredNumber(betaFaceConfidenceInput, "Face confidence", 0.001, 1)
          : 0.65,
        betaSpeakerConfidence: isCleanSpeakerBeta
          ? requiredNumber(betaSpeakerConfidenceInput, "Speaker confidence", 0.001, 1)
          : 0.65,
        betaWorkerCount: isCleanSpeakerBeta
          ? requiredNumber(betaWorkerCountInput, "Worker count", 1, 64, true)
          : 1,
        betaDevice: betaDeviceSelect.value,
        betaParallelDetectorStreams: betaParallelDetectorToggle.checked,
        betaKeepDebug: betaKeepDebugToggle.checked,
        betaReferenceAudio: betaReferenceAudioInput.value.trim(),
        betaIsolatedVideoProcesses: betaIsolatedModeToggle.checked,
        betaSkipFirstVideos: isCleanSpeakerBeta
          ? requiredNumber(betaSkipFirstInput, "Skip-first count", 0, 10000, true)
          : 0,
        betaSkipCompletedOutputs: betaSkipCompletedToggle.checked,
        betaVideoCooldownSeconds: isCleanSpeakerBeta
          ? requiredNumber(betaCooldownInput, "Video cooldown", 0, 3600)
          : 0,
      },
    });
    state.activeRunIds.procurement = Number(response.runId || 0) || null;
  } catch (error) {
    state.activeRunIds.procurement = null;
    setStatus(error.message);
    runSubtitle.textContent = error.message;
  }
}

async function checkBetaReadiness() {
  betaReadinessList.textContent = "Checking...";
  const report = await api(`/api/procurement-beta/readiness?token=${encodeURIComponent(launcherToken)}`);
  renderBetaReadiness(report);
}

function renderBetaReadiness(report) {
  const items = Array.isArray(report.items) ? report.items : [];
  betaReadinessList.innerHTML = "";
  const summary = document.createElement("div");
  summary.className = report.canProduceCleanSegments ? "readiness-summary ready" : "readiness-summary missing";
  summary.textContent = report.canProduceCleanSegments
    ? "Clean face and voice model stack is ready."
    : report.canRun
      ? "Required tools are available; install face and voice models for clean outputs."
      : "Install missing required tools before running YouTube/DOCX inputs.";
  betaReadinessList.appendChild(summary);
  items.forEach((item) => {
    const row = document.createElement("div");
    row.className = `readiness-row ${item.ready ? "ready" : "missing"}`;
    row.innerHTML = `<strong>${escapeHtml(item.label)}</strong><span>${item.ready ? "Ready" : item.required ? "Missing" : "Optional"}</span><small>${escapeHtml(item.detail || "")}</small>`;
    betaReadinessList.appendChild(row);
  });
}

// Audio has its own batch/single source picker, but uses the same backend
// process runner and progress channel as procurement.
function getSelectedAudioMode() {
  const checked = audioModeInputs.find((input) => input.checked);
  return checked ? checked.value : "batch";
}

function getVisibleAudioCatalogSources() {
  return visibleCatalogSources(catalogSources(state.audioCatalog), {
    filterField: audioCatalogFilterField.value,
    filterText: audioCatalogFilterText.value,
    sortField: audioCatalogSortField.value,
    sortDirection: audioCatalogSortDirection.value,
  });
}

function getAudioSelectedSourceIds() {
  if (!isCatalogScan(state.audioCatalog) || audioImportToggle.checked || getSelectedAudioMode() !== "batch") {
    return [];
  }
  return catalogSources(state.audioCatalog)
    .map((source) => String(source.source_id || source.id || ""))
    .filter((sourceId) => state.audioSelectedSourceIds.has(sourceId));
}

function configureAudioCatalogMetadataControls() {
  const fields = catalogMetadataFields(state.audioCatalog);
  const previousFilter = audioCatalogFilterField.value;
  const previousSort = audioCatalogSortField.value;
  audioCatalogFilterField.replaceChildren(new Option("All metadata", ""));
  audioCatalogSortField.replaceChildren(new Option("Catalog order", ""));
  fields.forEach((field) => {
    audioCatalogFilterField.appendChild(new Option(field, field));
    audioCatalogSortField.appendChild(new Option(field, field));
  });
  audioCatalogFilterField.value = fields.includes(previousFilter) ? previousFilter : "";
  audioCatalogSortField.value = fields.includes(previousSort) ? previousSort : "";
}

function clearAudioCatalogSelection() {
  state.audioCatalogLoadToken += 1;
  state.audioCatalog = null;
  state.audioSelectedSourceIds.clear();
  renderAudioCatalogSelection();
}

async function loadAudioCatalogSelection() {
  const sourcePath = audioSourcePathInput.value.trim();
  if (!sourcePath || audioImportToggle.checked || getSelectedAudioMode() !== "batch") {
    clearAudioCatalogSelection();
    return null;
  }
  const previousCatalog = state.audioCatalog;
  const previousSelection = new Set(state.audioSelectedSourceIds);
  const requestToken = ++state.audioCatalogLoadToken;
  state.audioCatalog = null;
  state.audioSelectedSourceIds.clear();
  renderAudioCatalogSelection();
  const payload = await api("/api/audio-catalog", {
    method: "POST",
    body: { sourcePath },
  });
  if (requestToken !== state.audioCatalogLoadToken || audioSourcePathInput.value.trim() !== sourcePath) {
    return null;
  }
  if (!payload.catalog) {
    renderAudioCatalogSelection();
    return payload;
  }
  const sameManifest = isCatalogScan(previousCatalog)
    && String(previousCatalog.source_path || "") === String(payload.source_path || "")
    && String(previousCatalog.catalog_sha256 || "") === String(payload.catalog_sha256 || "");
  state.audioCatalog = payload;
  const availableIds = catalogSources(payload).map((source) => String(source.source_id || source.id || ""));
  state.audioSelectedSourceIds = new Set(
    sameManifest ? availableIds.filter((sourceId) => previousSelection.has(sourceId)) : availableIds,
  );
  renderAudioCatalogSelection();
  return payload;
}

function renderAudioCatalogSelection() {
  const active = isCatalogScan(state.audioCatalog) && !audioImportToggle.checked && getSelectedAudioMode() === "batch";
  audioCatalogSelection.classList.toggle("hidden", !active);
  if (!active) {
    audioCatalogSourceList.replaceChildren();
    return;
  }
  configureAudioCatalogMetadataControls();
  const sources = catalogSources(state.audioCatalog);
  const visible = getVisibleAudioCatalogSources();
  const selectedCount = sources.filter((source) =>
    state.audioSelectedSourceIds.has(String(source.source_id || source.id || "")),
  ).length;
  audioCatalogSelectionSummary.textContent = `${plural(selectedCount, "source")} selected; ${plural(visible.length, "source")} visible.`;
  audioCatalogSourceList.replaceChildren();
  if (!visible.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No catalog sources match this metadata filter.";
    audioCatalogSourceList.appendChild(empty);
    return;
  }
  visible.forEach((source) => {
    const sourceId = String(source.source_id || source.id || "");
    const label = document.createElement("label");
    label.className = "audio-catalog-source-row";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.audioSelectedSourceIds.has(sourceId);
    checkbox.setAttribute("aria-label", `Analyse ${sourceId}`);
    checkbox.addEventListener("change", () => {
      state.audioSelectedSourceIds = setVisibleCatalogSelection(
        state.audioSelectedSourceIds,
        [source],
        checkbox.checked,
      );
      renderAudioCatalogSelection();
    });
    const description = document.createElement("span");
    const title = document.createElement("strong");
    title.textContent = `${sourceId} — ${source.title || source.link || "Untitled source"}`;
    const details = document.createElement("small");
    const metadata = Object.entries(source.metadata || {})
      .filter(([_field, value]) => String(value || "").trim())
      .map(([field, value]) => `${field}: ${value}`);
    details.textContent = [source.speaker || "Pooled (no speaker)", ...metadata].join(" · ");
    description.append(title, details);
    label.append(checkbox, description);
    audioCatalogSourceList.appendChild(label);
  });
}

function updateAudioMode() {
  state.audioMode = getSelectedAudioMode();
  const importing = audioImportToggle.checked;
  document.querySelectorAll("[data-audio-mode-option]").forEach((option) => {
    option.classList.toggle("active", option.dataset.audioModeOption === state.audioMode);
  });
  audioModeToggle.classList.toggle("hidden", importing);
  audioOptionsPanel.classList.toggle("hidden", importing);
  audioModeInputs.forEach((input) => {
    input.disabled = importing;
  });
  browseAudioFolderButton.classList.toggle("hidden", !importing && state.audioMode !== "batch");
  browseAudioVideoButton.classList.toggle("hidden", importing || state.audioMode !== "single");
  audioOutputRootInput.disabled = importing;
  browseAudioOutputButton.disabled = importing;
  audioStopOnErrorToggle.disabled = importing || state.audioMode !== "batch";
  audioSourcePathLabel.textContent = importing ? "Processed audio output folder" : "Audio source path";
  audioSourcePathInput.placeholder = importing
    ? "Paste an existing processed audio folder"
    : "Paste downloads folder or MP4 path";
  browseAudioFolderButton.textContent = importing ? "Select processed audio folder" : "Select input folder";
  runAudioButton.textContent = importing ? "Use imported audio outputs" : "Run audio processing";
  renderAudioCatalogSelection();
}

function getAnalysisSourceMethod(controls) {
  const checked = controls.methodInputs.find((input) => input.checked);
  return checked ? checked.value : "run";
}

function setAnalysisSourceMethod(controls, method) {
  controls.methodInputs.forEach((input) => {
    input.checked = input.value === method;
  });
}

function analysisModalityPayload(name, controls) {
  if (!controls.enabled.checked) {
    return null;
  }
  return {
    name,
    sourceMethod: getAnalysisSourceMethod(controls),
    sourcePath: controls.source.value.trim(),
  };
}

function buildAnalysisModalities() {
  return [
    analysisModalityPayload("imotions", analysisImotionsControls),
    analysisModalityPayload("audio", analysisAudioControls),
    analysisModalityPayload("text", analysisTextControls),
  ].filter(Boolean);
}

function buildAnalysisSpeakerGroups() {
  return state.analysisSpeakerGroups.map((group) => ({
    id: group.id,
    name: group.name.trim(),
    speakerKeys: [...group.speakerKeys],
  }));
}

function analysisModalitiesSignature(
  modalities = buildAnalysisModalities(),
  sourceManifest = analysisSourceManifestInput.value.trim(),
) {
  return JSON.stringify({ modalities, sourceManifest });
}

function hasCompleteAnalysisModality(modalities = buildAnalysisModalities()) {
  return modalities.length > 0 && modalities.every((modality) => Boolean(modality.sourcePath));
}

function parseAnalysisReferenceOverrides() {
  return parseFiniteReferenceOverridesText(analysisReferenceOverridesInput.value);
}

function hasAnalysisRunModality(modalities = buildAnalysisModalities()) {
  return modalities.some((modality) => modality.sourceMethod === "run");
}

function isAnalysisRunLocked() {
  return state.analysisSubmissionOperation.pending || Boolean(state.activeRunIds.analysis);
}

function analysisRunGateReasonsFromForm(modalities = buildAnalysisModalities()) {
  const currentSignature = analysisModalitiesSignature(modalities);
  return analysisRunGateReasons({
    modalities,
    outputRoot: analysisOutputRootInput.value,
    writeCombinedWorkbook: analysisWriteCombinedToggle.checked,
    discoverySignature: state.analysisDiscoverySignature,
    currentSignature,
    profileContext: state.analysisProfileContext,
    profileDraft: state.analysisProfileDraft,
    includeProbabilitySheets: analysisProbabilitySheetsToggle.checked,
    confidenceLevelText: analysisConfidenceLevelInput.value,
    headlinePolicy: analysisHeadlinePolicySelect.value,
    defaultReferenceText: analysisDefaultReferenceInput.value,
    referenceOverridesText: analysisReferenceOverridesInput.value,
  });
}

function analysisSubmissionSignature() {
  return JSON.stringify({
    modalities: buildAnalysisModalities(),
    outputRoot: analysisOutputRootInput.value.trim(),
    writeCombinedWorkbook: analysisWriteCombinedToggle.checked,
    includeConstructComparison: analysisConstructComparisonToggle.checked,
    includeProbabilitySheets: analysisProbabilitySheetsToggle.checked,
    confidenceLevel: String(analysisConfidenceLevelInput.value),
    headlinePolicy: analysisHeadlinePolicySelect.value,
    analysisProfile: state.analysisProfileContext && state.analysisProfileDraft
      ? buildAnalysisProfilePayload(state.analysisProfileContext, state.analysisProfileDraft)
      : null,
    defaultReference: String(analysisDefaultReferenceInput.value),
    referenceOverrides: analysisReferenceOverridesInput.value,
    writeGraphs: analysisGraphsToggle.checked,
    includeLogscale: analysisLogscaleToggle.checked,
    includeLandmarks: analysisLandmarksToggle.checked,
    includeTiming: analysisTimingToggle.checked,
    excludeGeometry: analysisExcludeGeometryToggle.checked,
  });
}

function renderAnalysisRunGateMessages(reasons) {
  analysisRunGateMessages.replaceChildren();
  if (!reasons.length) {
    const ready = document.createElement("p");
    ready.className = "analysis-run-ready";
    ready.textContent = "Ready to run.";
    analysisRunGateMessages.appendChild(ready);
    return;
  }
  const heading = document.createElement("p");
  heading.textContent = "Before running:";
  const list = document.createElement("ul");
  reasons.forEach((reason) => {
    const item = document.createElement("li");
    item.textContent = reason;
    list.appendChild(item);
  });
  analysisRunGateMessages.append(heading, list);
}

function shouldShowAnalysisFaceOptions() {
  return analysisImotionsEnabled.checked && getAnalysisSourceMethod(analysisImotionsControls) === "run";
}

function updateAnalysisCard(controls) {
  const enabled = controls.enabled.checked;
  const analysisLocked = isAnalysisRunLocked();
  const card = document.querySelector(`[data-analysis-modality="${controls.name}"]`);
  card.classList.toggle("disabled", !enabled);
  controls.enabled.disabled = analysisLocked;
  controls.methodInputs.forEach((input) => {
    input.disabled = !enabled || analysisLocked;
  });
  controls.source.disabled = !enabled || analysisLocked;
  controls.browse.disabled = !enabled || analysisLocked;
  const sourceMethod = getAnalysisSourceMethod(controls);
  const help = document.querySelector(`[data-analysis-help="${controls.name}"]`);
  help.textContent = sourceMethod === "import"
    ? controls.name === "text"
      ? "Choose completed text results containing multimodal/speaker_level_summary.csv."
      : "Choose an existing Analysis report folder. Source files will not be re-analysed."
    : controls.name === "imotions"
      ? "Choose the folder containing iMotions CSV exports."
      : "Choose the folder containing processed audio_analysis.csv files.";
}

function updateAnalysisForm() {
  analysisImplementedControls.forEach(updateAnalysisCard);

  const modalities = buildAnalysisModalities();
  const currentSignature = analysisModalitiesSignature(modalities);
  const discoveryRequestChanged = state.analysisDiscoveryOperation.pending
    && state.analysisDiscoveryOperation.signature !== currentSignature;
  const completedDiscoveryChanged = state.analysisDiscoverySignature
    && state.analysisDiscoverySignature !== currentSignature;
  if (discoveryRequestChanged) {
    invalidateAnalysisAsyncOperation(state.analysisDiscoveryOperation);
  }
  if (discoveryRequestChanged || completedDiscoveryChanged) {
    state.analysisDiscoverySignature = "";
    state.analysisSpeakers = [];
    state.analysisSpeakerGroups = [];
    state.analysisProfileContext = null;
    state.analysisProfileDraft = null;
    analysisSpeakerDiscoveryStatus.textContent = "Sources changed. Load source metadata again.";
    renderAnalysisCustomization();
  }

  const completeSources = hasCompleteAnalysisModality(modalities);
  const submissionPending = state.analysisSubmissionOperation.pending;
  const analysisLocked = isAnalysisRunLocked();
  const combinedEnabled = analysisWriteCombinedToggle.checked;
  if (!combinedEnabled && state.analysisDiscoveryOperation.pending) {
    invalidateAnalysisAsyncOperation(state.analysisDiscoveryOperation);
  }
  const importOnly = modalities.length > 0 && !hasAnalysisRunModality(modalities);
  analysisFaceAdvanced.classList.toggle("hidden", !shouldShowAnalysisFaceOptions());
  analysisGraphsOption.classList.toggle("hidden", importOnly);
  analysisLogscaleOption.classList.toggle("hidden", importOnly);
  analysisGraphsToggle.disabled = importOnly || analysisLocked;
  analysisLogscaleToggle.disabled = importOnly || analysisLocked;
  analysisWriteCombinedToggle.disabled = analysisLocked;
  analysisConstructComparisonToggle.disabled = !combinedEnabled || analysisLocked;
  analysisProbabilitySheetsToggle.disabled = !combinedEnabled || analysisLocked;
  analysisHeadlinePolicySelect.disabled = !combinedEnabled || analysisLocked;
  const probabilityEnabled = combinedEnabled && analysisProbabilitySheetsToggle.checked;
  analysisConfidenceLevelInput.disabled = !probabilityEnabled || analysisLocked;
  analysisDefaultReferenceInput.disabled = !probabilityEnabled || analysisLocked;
  analysisReferenceOverridesInput.disabled = !probabilityEnabled || analysisLocked;
  analysisOutputRootInput.disabled = analysisLocked;
  browseAnalysisOutputButton.disabled = analysisLocked;
  analysisSourceManifestInput.disabled = !combinedEnabled || analysisLocked;
  browseAnalysisSourceManifestButton.disabled = !combinedEnabled || analysisLocked;
  analysisLandmarksToggle.disabled = analysisLocked;
  analysisTimingToggle.disabled = analysisLocked;
  analysisExcludeGeometryToggle.disabled = analysisLocked;
  discoverAnalysisSpeakersButton.disabled = !combinedEnabled
    || !completeSources
    || state.analysisDiscoveryOperation.pending
    || analysisLocked;
  addAnalysisSpeakerGroupButton.disabled = !combinedEnabled
    || !state.analysisProfileContext
    || analysisLocked;
  analysisSpeakerGroups.querySelectorAll("input, button").forEach((control) => {
    control.disabled = !combinedEnabled || analysisLocked || control.dataset.assignmentLocked === "true";
  });
  analysisSortFields.querySelectorAll("input, button").forEach((control) => {
    control.disabled = !combinedEnabled
      || analysisLocked
      || control.dataset.analysisSortUnavailable === "true";
  });
  analysisMetadataFilters.querySelectorAll("input").forEach((control) => {
    control.disabled = !combinedEnabled || analysisLocked;
  });
  analysisAutomaticGroupField.disabled = !combinedEnabled || !state.analysisProfileContext || analysisLocked;
  openAnalysisCustomizeButton.disabled = !combinedEnabled || analysisLocked;
  saveAnalysisCustomizationButton.disabled = !state.analysisProfileContext
    || analysisProfileIssues(
      state.analysisProfileContext,
      state.analysisProfileDraft,
      buildAnalysisModalities().some((modality) => modality.name === "text"),
    ).length > 0
    || analysisLocked;

  const reasons = analysisRunGateReasonsFromForm(modalities);
  if (state.analysisDiscoveryOperation.pending && combinedEnabled) {
    reasons.unshift("Wait for speaker discovery to finish.");
  }
  if (state.activeRunIds.analysis) {
    reasons.splice(0, reasons.length, "Analysis is running. Controls unlock when the run finishes or stops.");
  } else if (submissionPending) {
    reasons.splice(0, reasons.length, "Analysis is starting. Please wait.");
  }
  renderAnalysisRunGateMessages(reasons);
  runAnalysisButton.disabled = reasons.length > 0;
  runAnalysisButton.textContent = state.activeRunIds.analysis
    ? "Analysis running..."
    : submissionPending
      ? "Starting analysis..."
      : reasons.length
        ? "Review requirements"
        : "Run analysis";
  renderAnalysisProfileSummary();
}

function createSensibleAnalysisGroups(speakers) {
  if (!speakers.length) {
    return [];
  }
  return [{
    id: `analysis-group-${state.nextAnalysisGroupId++}`,
    name: "All speakers",
    speakerKeys: speakers.map((speaker) => speaker.key),
  }];
}

function analysisManualGroups() {
  return state.analysisProfileDraft?.manualGroups || [];
}

function profileMemberSourceIds(member) {
  if (!state.analysisProfileContext) return [];
  if (member.type === "source") return [member.id];
  return state.analysisProfileContext.speakers
    .find((speaker) => speaker.id === member.id)?.sourceIds || [];
}

function profileMemberConflict(groupId, type, id) {
  const candidateIds = new Set(profileMemberSourceIds({ type, id }));
  for (const group of analysisManualGroups()) {
    for (const member of group.members || []) {
      if (group.id === groupId && member.type === type && member.id === id) continue;
      if (profileMemberSourceIds(member).some((sourceId) => candidateIds.has(sourceId))) {
        return group.name || "another manual group";
      }
    }
  }
  return "";
}

function assignAnalysisProfileMember(groupId, type, id, selected) {
  const group = analysisManualGroups().find((candidate) => candidate.id === groupId);
  if (!group) return;
  group.members = (group.members || []).filter((member) => member.type !== type || member.id !== id);
  if (selected) {
    const conflict = profileMemberConflict(groupId, type, id);
    if (conflict) {
      setStatus(`This selection overlaps ${conflict}. A source can belong to only one manual group.`);
      refreshAnalysisSpeakerGroupState();
      updateAnalysisForm();
      return;
    }
    group.members.push({ type, id });
  }
  refreshAnalysisSpeakerGroupState();
  renderAnalysisProfilePreview();
  updateAnalysisForm();
}

function assignAnalysisSpeaker(groupId, speakerKey, selected) {
  assignAnalysisProfileMember(groupId, "speaker", speakerKey, selected);
}

function removeAnalysisSpeakerGroup(groupId) {
  const groups = analysisManualGroups();
  const removedIndex = groups.findIndex((group) => group.id === groupId);
  if (removedIndex < 0) {
    return;
  }
  groups.splice(removedIndex, 1);
  const adjacentGroup = groups[Math.min(removedIndex, groups.length - 1)];
  renderAnalysisCustomization(adjacentGroup ? `group-name:${adjacentGroup.id}` : "");
  updateAnalysisForm();
  if (!adjacentGroup) {
    addAnalysisSpeakerGroupButton.focus();
  }
}

function addAnalysisSpeakerGroup() {
  if (!state.analysisProfileDraft) {
    setStatus("Load source metadata before adding a manual group.");
    return;
  }
  const number = state.nextAnalysisGroupId++;
  const groupId = `analysis-group-${number}`;
  state.analysisProfileDraft.manualGroups.push({
    id: groupId,
    name: `Manual group ${state.analysisProfileDraft.manualGroups.length + 1}`,
    members: [],
  });
  renderAnalysisCustomization(`group-name:${groupId}`);
  updateAnalysisForm();
}

function syncAnalysisGroupAccessibleNames(row, group) {
  const removeButton = row.querySelector("[data-analysis-remove-group]");
  if (removeButton) {
    removeButton.setAttribute("aria-label", analysisGroupAccessibleLabels(group.name).remove);
  }
  row.querySelectorAll("[data-analysis-speaker-name]").forEach((checkbox) => {
    checkbox.setAttribute(
      "aria-label",
      analysisGroupAccessibleLabels(group.name, checkbox.dataset.analysisSpeakerName).assign,
    );
  });
}

function announceAnalysisGroupWarnings() {
  if (analysisWarningAnnouncementTimer !== null) {
    window.clearTimeout(analysisWarningAnnouncementTimer);
  }
  const warningText = state.analysisProfileContext
    ? analysisProfileIssues(
      state.analysisProfileContext,
      state.analysisProfileDraft,
      buildAnalysisModalities().some((modality) => modality.name === "text"),
    ).join(" ")
    : "";
  analysisGroupWarningStatus.textContent = "";
  if (!warningText) {
    analysisWarningAnnouncementTimer = null;
    return;
  }
  analysisWarningAnnouncementTimer = window.setTimeout(() => {
    analysisGroupWarningStatus.textContent = warningText;
    analysisWarningAnnouncementTimer = null;
  }, 0);
}

function renderAnalysisSpeakerGroups(preferredFocusKey = "") {
  const activeElement = document.activeElement;
  const previousFocusKey = analysisSpeakerGroups.contains(activeElement)
    ? activeElement.getAttribute("data-analysis-focus") || ""
    : "";
  analysisSpeakerGroups.replaceChildren();
  if (!state.analysisProfileContext) {
    const empty = document.createElement("p");
    empty.className = "analysis-group-empty";
    empty.textContent = "No source metadata loaded yet.";
    analysisSpeakerGroups.appendChild(empty);
    announceAnalysisGroupWarnings();
    return;
  }
  const context = state.analysisProfileContext;
  analysisManualGroups().forEach((group, groupIndex) => {
    const row = document.createElement("section");
    row.className = "analysis-speaker-group";
    row.dataset.analysisGroupId = group.id;
    const warningId = `analysis-group-warning-${groupIndex + 1}`;
    row.setAttribute("aria-describedby", warningId);

    const header = document.createElement("div");
    header.className = "analysis-speaker-group-head";
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.value = group.name;
    nameInput.setAttribute("aria-label", "Manual group name");
    nameInput.setAttribute("aria-describedby", warningId);
    nameInput.setAttribute("data-analysis-focus", `group-name:${group.id}`);
    nameInput.addEventListener("input", () => {
      group.name = nameInput.value;
      syncAnalysisGroupAccessibleNames(row, group);
      updateAnalysisForm();
    });
    const removeButton = document.createElement("button");
    removeButton.type = "button";
    removeButton.className = "ghost-button";
    removeButton.textContent = "Remove group";
    removeButton.setAttribute("aria-describedby", warningId);
    removeButton.setAttribute("data-analysis-remove-group", "true");
    removeButton.setAttribute("data-analysis-focus", `group-remove:${group.id}`);
    removeButton.addEventListener("click", () => removeAnalysisSpeakerGroup(group.id));
    header.append(nameInput, removeButton);

    const choices = document.createElement("div");
    choices.className = "analysis-speaker-choices";
    const speakerHeading = document.createElement("strong");
    speakerHeading.textContent = "Speakers";
    choices.appendChild(speakerHeading);
    context.speakers.forEach((speaker) => {
      const label = document.createElement("label");
      label.className = "analysis-speaker-choice";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = (group.members || []).some((member) => member.type === "speaker" && member.id === speaker.id);
      checkbox.dataset.assignmentLocked = String(!checkbox.checked && Boolean(profileMemberConflict(group.id, "speaker", speaker.id)));
      checkbox.disabled = checkbox.dataset.assignmentLocked === "true";
      checkbox.setAttribute("aria-describedby", warningId);
      checkbox.setAttribute("data-analysis-speaker-name", speaker.name);
      checkbox.setAttribute("data-analysis-focus", `member:${group.id}:speaker:${speaker.id}`);
      checkbox.dataset.analysisGroupId = group.id;
      checkbox.dataset.analysisMemberType = "speaker";
      checkbox.dataset.analysisMemberId = speaker.id;
      checkbox.addEventListener("change", () => assignAnalysisProfileMember(group.id, "speaker", speaker.id, checkbox.checked));
      const name = document.createElement("span");
      name.textContent = `${speaker.name} (${speaker.sourceIds.length} source${speaker.sourceIds.length === 1 ? "" : "s"})`;
      label.append(checkbox, name);
      choices.appendChild(label);
    });

    const sourceHeading = document.createElement("strong");
    sourceHeading.textContent = "Individual sources";
    choices.appendChild(sourceHeading);
    context.sources.forEach((source) => {
      const label = document.createElement("label");
      label.className = "analysis-speaker-choice";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = (group.members || []).some((member) => member.type === "source" && member.id === source.id);
      checkbox.dataset.assignmentLocked = String(!checkbox.checked && Boolean(profileMemberConflict(group.id, "source", source.id)));
      checkbox.disabled = checkbox.dataset.assignmentLocked === "true";
      checkbox.setAttribute("data-analysis-speaker-name", `${source.title}, ${source.speaker}`);
      checkbox.setAttribute("data-analysis-focus", `member:${group.id}:source:${source.id}`);
      checkbox.dataset.analysisGroupId = group.id;
      checkbox.dataset.analysisMemberType = "source";
      checkbox.dataset.analysisMemberId = source.id;
      checkbox.addEventListener("change", () => assignAnalysisProfileMember(group.id, "source", source.id, checkbox.checked));
      const name = document.createElement("span");
      name.textContent = `${source.title} — ${source.speaker} (${source.id})`;
      label.append(checkbox, name);
      choices.appendChild(label);
    });

    const warning = document.createElement("p");
    warning.className = "analysis-group-warning";
    warning.id = warningId;
    const warningText = !(group.members || []).length ? "Add at least one speaker or individual source." : "";
    warning.classList.toggle("hidden", !warningText);
    warning.textContent = warningText;
    row.append(header, choices, warning);
    syncAnalysisGroupAccessibleNames(row, group);
    analysisSpeakerGroups.appendChild(row);
  });
  const focusControls = Array.from(analysisSpeakerGroups.querySelectorAll("[data-analysis-focus]"));
  const focusKey = chooseAnalysisFocusKey(
    preferredFocusKey,
    previousFocusKey,
    focusControls.map((control) => control.getAttribute("data-analysis-focus")),
  );
  const focusTarget = focusControls
    .find((control) => control.getAttribute("data-analysis-focus") === focusKey);
  focusTarget?.focus();
  announceAnalysisGroupWarnings();
}

function refreshAnalysisSpeakerGroupState() {
  analysisSpeakerGroups.querySelectorAll("[data-analysis-member-type]").forEach((checkbox) => {
    const group = analysisManualGroups().find((candidate) => candidate.id === checkbox.dataset.analysisGroupId);
    const checked = Boolean(group?.members?.some(
      (member) => member.type === checkbox.dataset.analysisMemberType
        && member.id === checkbox.dataset.analysisMemberId,
    ));
    checkbox.checked = checked;
    checkbox.dataset.assignmentLocked = String(
      !checked && Boolean(profileMemberConflict(
        checkbox.dataset.analysisGroupId,
        checkbox.dataset.analysisMemberType,
        checkbox.dataset.analysisMemberId,
      )),
    );
  });
  analysisSpeakerGroups.querySelectorAll(".analysis-speaker-group").forEach((row) => {
    const groupId = row.dataset.analysisGroupId;
    const group = analysisManualGroups().find((candidate) => candidate.id === groupId);
    const warning = row.querySelector(".analysis-group-warning");
    if (!warning) return;
    const warningText = group && !(group.members || []).length
      ? "Add at least one speaker or individual source."
      : "";
    warning.classList.toggle("hidden", !warningText);
    warning.textContent = warningText;
  });
  announceAnalysisGroupWarnings();
}

function refreshAnalysisProfileFieldRows() {
  if (!state.analysisProfileDraft) return;
  const draft = state.analysisProfileDraft;
  analysisSortFields.querySelectorAll("[data-analysis-sort-field]").forEach((row) => {
    const fieldName = row.dataset.analysisSortField;
    const priority = draft.sortFields.indexOf(fieldName);
    row.querySelector("input").checked = priority >= 0;
    row.querySelector("span").textContent = priority >= 0 ? `${priority + 1}. ${fieldName}` : fieldName;
    row.querySelectorAll("button").forEach((button) => {
      const offset = Number(button.dataset.analysisSortOffset);
      button.classList.toggle("hidden", priority < 0);
      button.dataset.analysisSortUnavailable = String(
        priority < 0 || priority + offset < 0 || priority + offset >= draft.sortFields.length,
      );
      button.disabled = button.dataset.analysisSortUnavailable === "true";
    });
  });
}

function renderAnalysisProfileFields() {
  analysisSortFields.replaceChildren();
  analysisAutomaticGroupField.replaceChildren();
  const noGrouping = document.createElement("option");
  noGrouping.value = "";
  noGrouping.textContent = "No metadata grouping";
  analysisAutomaticGroupField.appendChild(noGrouping);
  if (!state.analysisProfileContext || !state.analysisProfileDraft) return;
  const draft = state.analysisProfileDraft;
  state.analysisProfileContext.metadataFields.forEach((field) => {
    const row = document.createElement("div");
    row.className = "analysis-profile-field-row";
    row.dataset.analysisSortField = field.name;
    const label = document.createElement("label");
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = draft.sortFields.includes(field.name);
    checkbox.addEventListener("change", () => {
      draft.sortFields = draft.sortFields.filter((name) => name !== field.name);
      if (checkbox.checked) draft.sortFields.push(field.name);
      refreshAnalysisProfileFieldRows();
      renderAnalysisProfilePreview();
      updateAnalysisForm();
    });
    const text = document.createElement("span");
    text.textContent = field.name;
    label.append(checkbox, text);
    row.appendChild(label);
    [["Move up", -1], ["Move down", 1]].forEach(([title, offset]) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "ghost-button compact-button";
      button.textContent = offset < 0 ? "↑" : "↓";
      button.dataset.analysisSortOffset = String(offset);
      button.setAttribute("aria-label", `${title}: ${field.name}`);
      button.addEventListener("click", () => {
        const priority = draft.sortFields.indexOf(field.name);
        const target = priority + offset;
        if (priority < 0 || target < 0 || target >= draft.sortFields.length) return;
        [draft.sortFields[priority], draft.sortFields[target]] = [draft.sortFields[target], draft.sortFields[priority]];
        refreshAnalysisProfileFieldRows();
        renderAnalysisProfilePreview();
        updateAnalysisForm();
      });
      row.appendChild(button);
    });
    analysisSortFields.appendChild(row);
    const option = document.createElement("option");
    option.value = field.name;
    option.textContent = field.name;
    analysisAutomaticGroupField.appendChild(option);
  });
  refreshAnalysisProfileFieldRows();
  analysisAutomaticGroupField.value = draft.automaticGroupField;
}

function renderAnalysisMetadataFilters() {
  analysisMetadataFilters.replaceChildren();
  if (!state.analysisProfileContext || !state.analysisProfileDraft) return;
  state.analysisProfileContext.metadataFields.forEach((field) => {
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    const selected = state.analysisProfileDraft.metadataFilters[field.name] || [];
    summary.textContent = `${field.name}: ${selected.length} of ${field.values.length} visible`;
    details.appendChild(summary);
    const choices = document.createElement("div");
    choices.className = "analysis-filter-values";
    field.values.forEach((value) => {
      const label = document.createElement("label");
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = selected.includes(value);
      checkbox.addEventListener("change", () => {
        const values = new Set(state.analysisProfileDraft.metadataFilters[field.name] || []);
        if (checkbox.checked) values.add(value); else values.delete(value);
        state.analysisProfileDraft.metadataFilters[field.name] = field.values.filter((candidate) => values.has(candidate));
        summary.textContent = `${field.name}: ${state.analysisProfileDraft.metadataFilters[field.name].length} of ${field.values.length} visible`;
        renderAnalysisProfilePreview();
        updateAnalysisForm();
      });
      const text = document.createElement("span");
      text.textContent = value;
      label.append(checkbox, text);
      choices.appendChild(label);
    });
    details.appendChild(choices);
    analysisMetadataFilters.appendChild(details);
  });
}

function renderAnalysisProfilePreview() {
  analysisProfilePreview.replaceChildren();
  if (!state.analysisProfileContext || !state.analysisProfileDraft) {
    analysisProfilePreview.textContent = "Load source metadata to preview the output.";
    return;
  }
  const sourceById = new Map(state.analysisProfileContext.sources.map((source) => [source.id, source]));
  const preview = resolveAnalysisProfilePreview(state.analysisProfileContext, state.analysisProfileDraft);
  const summary = document.createElement("p");
  summary.textContent = `${preview.orderedSourceIds.length} source${preview.orderedSourceIds.length === 1 ? "" : "s"} in ${preview.groups.filter((group) => group.sourceIds.length).length} output group${preview.groups.filter((group) => group.sourceIds.length).length === 1 ? "" : "s"}.`;
  const list = document.createElement("ol");
  preview.groups.filter((group) => group.sourceIds.length).forEach((group) => {
    const item = document.createElement("li");
    const heading = document.createElement("strong");
    heading.textContent = group.name;
    const sources = document.createElement("span");
    sources.textContent = group.sourceIds.map((sourceId) => sourceById.get(sourceId)?.title || sourceId).join(" → ");
    item.append(heading, sources);
    list.appendChild(item);
  });
  analysisProfilePreview.append(summary, list);
}

function renderAnalysisProfileSummary() {
  if (!state.analysisProfileContext || !state.analysisProfileDraft) {
    analysisProfileSummary.textContent = "No output customization loaded. Open Customize output after choosing source folders.";
    return;
  }
  const preview = resolveAnalysisProfilePreview(state.analysisProfileContext, state.analysisProfileDraft);
  const groupCount = preview.groups.filter((group) => group.sourceIds.length).length;
  const sortCopy = state.analysisProfileDraft.sortFields.length
    ? `Sorted by ${state.analysisProfileDraft.sortFields.join(" then ")}.`
    : "Source-manifest order retained.";
  const issueCount = analysisProfileIssues(
    state.analysisProfileContext,
    state.analysisProfileDraft,
    buildAnalysisModalities().some((modality) => modality.name === "text"),
  ).length;
  analysisProfileSummary.textContent = `${preview.orderedSourceIds.length} sources, ${groupCount} groups. ${sortCopy}${issueCount ? ` ${issueCount} item${issueCount === 1 ? "" : "s"} need review.` : " Ready."}`;
}

function renderAnalysisCustomization(preferredFocusKey = "") {
  renderAnalysisProfileFields();
  renderAnalysisMetadataFilters();
  renderAnalysisSpeakerGroups(preferredFocusKey);
  renderAnalysisProfilePreview();
  renderAnalysisProfileSummary();
}

async function discoverAnalysisSpeakers() {
  const modalities = buildAnalysisModalities();
  if (!hasCompleteAnalysisModality(modalities)) {
    setStatus("Complete at least one analysis source before loading source metadata.");
    return;
  }
  const signature = analysisModalitiesSignature(modalities);
  const token = beginAnalysisAsyncOperation(state.analysisDiscoveryOperation, signature);
  if (!token) {
    return;
  }
  analysisSpeakerDiscoveryStatus.textContent = "Loading source metadata...";
  updateAnalysisForm();
  try {
    const sourceManifest = analysisSourceManifestInput.value.trim();
    const payload = await api("/api/analysis-profile-context", {
      method: "POST",
      body: sourceManifest ? { modalities, sourceManifest } : { modalities },
    });
    if (!isAnalysisAsyncOperationCurrent(
      state.analysisDiscoveryOperation,
      token,
      analysisModalitiesSignature(),
    )) {
      return;
    }
    if (
      !payload
      || typeof payload.sourceManifest !== "string"
      || !/^[0-9a-f]{64}$/i.test(payload.sourceManifestSha256 || "")
      || !Array.isArray(payload.metadataFields)
      || !Array.isArray(payload.speakers)
      || !Array.isArray(payload.sources)
    ) {
      throw new Error("The launcher returned incomplete source metadata.");
    }
    state.analysisProfileContext = payload;
    state.analysisProfileDraft = createAnalysisProfileDraft(payload);
    state.analysisSpeakers = payload.speakers.map((speaker) => ({
      key: speaker.id,
      name: speaker.name,
      availableIn: [],
    }));
    state.analysisSpeakerGroups = [];
    state.analysisDiscoverySignature = signature;
    analysisSpeakerDiscoveryStatus.textContent = `${payload.sources.length} sources and ${payload.speakers.length} speakers loaded from ${payload.sourceManifest}.`;
    renderAnalysisCustomization();
    setStatus("Output customization ready for review");
  } catch (error) {
    if (!isAnalysisAsyncOperationCurrent(
      state.analysisDiscoveryOperation,
      token,
      analysisModalitiesSignature(),
    )) {
      return;
    }
    state.analysisDiscoverySignature = "";
    state.analysisSpeakers = [];
    state.analysisSpeakerGroups = [];
    state.analysisProfileContext = null;
    state.analysisProfileDraft = null;
    renderAnalysisCustomization();
    analysisSpeakerDiscoveryStatus.textContent = error.message;
    setStatus(error.message);
  } finally {
    if (finishAnalysisAsyncOperation(state.analysisDiscoveryOperation, token)) {
      updateAnalysisForm();
    }
  }
}

async function openAnalysisCustomization() {
  await showScreen("analysis-customize");
  renderAnalysisCustomization();
  const modalities = buildAnalysisModalities();
  if (
    hasCompleteAnalysisModality(modalities)
    && (!state.analysisProfileContext || state.analysisDiscoverySignature !== analysisModalitiesSignature(modalities))
  ) {
    await discoverAnalysisSpeakers();
  }
}

async function saveAnalysisCustomization() {
  const issues = analysisProfileIssues(
    state.analysisProfileContext,
    state.analysisProfileDraft,
    buildAnalysisModalities().some((modality) => modality.name === "text"),
  );
  if (issues.length) {
    setStatus(issues[0]);
    updateAnalysisForm();
    return;
  }
  renderAnalysisProfileSummary();
  await showScreen("analysis-input");
  setStatus("Output customization saved for this Analysis run.");
  updateAnalysisForm();
}

async function runAudioProcessing() {
  const sourcePath = audioSourcePathInput.value.trim();
  if (!sourcePath) {
    setStatus("Choose an audio source first.");
    showScreen("audio-input");
    return;
  }
  audioProgressBar.style.width = "0%";
  audioProgressLabel.textContent = "Starting...";
  audioNextStep.classList.add("hidden");
  if (audioImportToggle.checked) {
    try {
      const validatedPath = await validateUiPath(sourcePath, "folder", "Audio import");
      state.workflow.imports.audio = validatedPath;
      audioSourcePathInput.value = validatedPath;
    } catch (error) {
      setStatus(error.message);
      return;
    }
    audioImportHubToggle.checked = true;
    audioImportHubPathInput.value = state.workflow.imports.audio;
    workflowAudioMethod.value = "import";
    workflowAudioImportPath.value = state.workflow.imports.audio;
    await showScreen("audio-run");
    audioProgressBar.style.width = "100%";
    audioProgressLabel.textContent = "Imported audio outputs selected";
    audioNextStep.classList.remove("hidden");
    setStatus("Audio import ready");
    return;
  }
  state.pendingAudioOutput = "";
  setStatus("Starting audio");
  try {
    if (getSelectedAudioMode() === "batch") {
      await loadAudioCatalogSelection();
      if (audioSourcePathInput.value.trim() !== sourcePath) {
        throw new Error("Audio source changed while its catalog manifest was loading. Review it again.");
      }
    }
    const selectedSourceIds = getAudioSelectedSourceIds();
    if (isCatalogScan(state.audioCatalog) && !selectedSourceIds.length) {
      throw new Error("Select at least one catalog source for audio processing.");
    }
    const response = await api("/api/run-audio", {
      method: "POST",
      body: {
        mode: getSelectedAudioMode(),
        sourcePath,
        outputRoot: audioOutputRootInput.value.trim(),
        windowSeconds: requiredNumber(audioWindowSecondsInput, "Audio window length", 0.5, 120),
        strideSeconds: requiredNumber(audioStrideSecondsInput, "Audio stride length", 0.5, 120),
        opensmileFeatureSet: audioFeatureSetSelect.value,
        includeEmotions: audioEmotionsToggle.checked,
        device: audioDeviceSelect.value,
        keepTempAudio: audioKeepTempToggle.checked,
        debug: audioDebugToggle.checked,
        stopOnError: audioStopOnErrorToggle.checked,
        selectedSourceIds: getAudioSelectedSourceIds(),
        catalogSha256: selectedSourceIds.length && isCatalogScan(state.audioCatalog)
          ? String(state.audioCatalog.catalog_sha256 || "")
          : "",
      },
    });
    state.activeRunIds.audio = Number(response.runId || 0) || null;
    state.pendingAudioOutput = audioOutputRootInput.value.trim();
    await showScreen("audio-run");
    setStatus("Running audio");
  } catch (error) {
    state.activeRunIds.audio = null;
    state.pendingAudioOutput = "";
    setStatus(error.message);
    audioProgressLabel.textContent = error.message;
  }
}

async function runAnalysis() {
  if (state.activeRunIds.analysis) {
    setStatus("Analysis is already running.");
    updateAnalysisForm();
    return;
  }
  const modalities = buildAnalysisModalities();
  const gateReasons = analysisRunGateReasonsFromForm(modalities);
  if (gateReasons.length) {
    setStatus(gateReasons[0]);
    updateAnalysisForm();
    await showScreen("analysis-input");
    return;
  }
  const outputRoot = analysisOutputRootInput.value.trim();
  const submissionSignature = analysisSubmissionSignature();
  const token = beginAnalysisAsyncOperation(state.analysisSubmissionOperation, submissionSignature);
  if (!token) {
    return;
  }

  const writeCombinedWorkbook = analysisWriteCombinedToggle.checked;
  const includeConstructComparison = writeCombinedWorkbook && analysisConstructComparisonToggle.checked;
  const includeProbabilitySheets = writeCombinedWorkbook && analysisProbabilitySheetsToggle.checked;
  const confidenceLevel = includeProbabilitySheets
    ? Number(String(analysisConfidenceLevelInput.value).trim()) / 100
    : 0.95;
  const headlinePolicy = analysisHeadlinePolicySelect.value;
  const defaultReference = includeProbabilitySheets
    ? Number(String(analysisDefaultReferenceInput.value).trim())
    : 0;
  const referenceOverrides = includeProbabilitySheets ? parseAnalysisReferenceOverrides() : {};
  const analysisProfile = writeCombinedWorkbook && state.analysisProfileContext && state.analysisProfileDraft
    ? buildAnalysisProfilePayload(state.analysisProfileContext, state.analysisProfileDraft)
    : null;
  const options = {
    writeGraphs: analysisGraphsToggle.checked,
    includeLogscale: analysisLogscaleToggle.checked,
    includeLandmarks: shouldShowAnalysisFaceOptions() && analysisLandmarksToggle.checked,
    includeTiming: shouldShowAnalysisFaceOptions() && analysisTimingToggle.checked,
    excludeGeometry: shouldShowAnalysisFaceOptions() && analysisExcludeGeometryToggle.checked,
  };
  let runAccepted = false;
  analysisProgressBar.style.width = "0%";
  analysisProgressLabel.textContent = "Validating sources...";
  setStatus("Validating analysis sources");
  updateAnalysisForm();
  try {
    const validatedModalities = [];
    for (const modality of modalities) {
      const validatedPath = await validateUiPath(modality.sourcePath, "folder", `${modality.name} Analysis source`);
      if (!isAnalysisAsyncOperationCurrent(
        state.analysisSubmissionOperation,
        token,
        analysisSubmissionSignature(),
      )) {
        return;
      }
      validatedModalities.push({ ...modality, sourcePath: validatedPath });
    }
    const request = buildAnalysisWorkflowRequest({
      modalities: validatedModalities,
      outputRoot,
      writeCombinedWorkbook,
      includeConstructComparison,
      includeProbabilitySheets,
      confidenceLevel,
      headlinePolicy,
      defaultReference,
      referenceOverrides,
      speakerGroups: [],
      analysisProfile,
      ...options,
    });
    analysisProgressLabel.textContent = "Starting...";
    setStatus("Starting analysis");
    const response = await api("/api/run-analysis-workflow", {
      method: "POST",
      body: request,
    });
    if (!isAnalysisAsyncOperationCurrent(
      state.analysisSubmissionOperation,
      token,
      analysisSubmissionSignature(),
    )) {
      return;
    }
    const runId = Number(response.runId || 0) || null;
    if (!runId) {
      throw new Error("The Analysis launcher did not return a run identifier.");
    }
    state.activeRunIds.analysis = runId;
    runAccepted = true;
    await showScreen("analysis-run");
    setStatus("Running analysis");
  } catch (error) {
    if (!runAccepted && isAnalysisAsyncOperationCurrent(
      state.analysisSubmissionOperation,
      token,
      analysisSubmissionSignature(),
    )) {
      setStatus(error.message);
      analysisProgressLabel.textContent = error.message;
      await showScreen("analysis-input");
    } else if (runAccepted) {
      setStatus(`Analysis started, but the run screen could not open: ${error.message}`);
    }
  } finally {
    if (finishAnalysisAsyncOperation(state.analysisSubmissionOperation, token)) {
      updateAnalysisForm();
    }
  }
}

// Focus selections are written as a manifest file so the Python procurement
// tool can run independently from the browser session.
function createSegmentManifest() {
  const selectedSegments = [];
  getSelectedVideos().forEach((video) => {
    const segments = getSegments(video.id);
    segments.forEach((segment, index) => {
      selectedSegments.push({
        source_id: video.source_id || video.id || null,
        video_id: video.video_id || null,
        video_title: video.title || null,
        speaker: video.speaker,
        source_path: video.source_path,
        source_kind: video.source_kind,
        youtube_url: video.youtube_url || null,
        metadata: { ...(video.metadata || {}) },
        youtube_language: video.youtube_language || "",
        segment_index: index + 1,
        start_seconds: segment.start,
        end_seconds: segment.end,
        length_seconds: roundSecond(segment.end - segment.start),
        start_timecode: secondsToExtractorClock(segment.start),
        end_timecode: secondsToExtractorClock(segment.end),
      });
    });
  });
  return {
    schema_version: 1,
    source_path: state.scan ? state.scan.source_path : null,
    source_kind: state.scan ? state.scan.source_kind : null,
    gap_seconds: Math.max(0, Math.min(60, Number(focusGapInput.value) || 0)),
    selected_total_seconds: roundSecond(selectedSegments.reduce((sum, segment) => sum + segment.length_seconds, 0)),
    selected_segments: selectedSegments,
  };
}

// The backend owns process execution; this poller only reflects its current
// state into whichever run screen is active.
async function pollState() {
  try {
    const payload = await api(state.settingsLoaded ? "/api/state" : "/api/state?configuration=1");
    if (!outputRootInput.value && payload.defaultOutputRoot) {
      outputRootInput.value = payload.defaultOutputRoot;
    }
    if (!audioOutputRootInput.value && payload.defaultAudioOutputRoot) {
      audioOutputRootInput.value = payload.defaultAudioOutputRoot;
    }
    if (!analysisOutputRootInput.value && payload.defaultAnalysisOutputRoot) {
      analysisOutputRootInput.value = payload.defaultAnalysisOutputRoot;
      updateAnalysisForm();
    }
    if (!state.settingsLoaded && payload.settings) {
      applySettings(payload.settings);
    }
    if (payload.access) {
      applyAccess(payload.access);
    }
    const progress = payload.progress || {};
    const progressMode = String(progress.mode || "");
    const isAudioRun = progressMode.startsWith("audio-");
    const isAnalysisRun = progressMode.startsWith("analysis-");
    const runKind = isAnalysisRun ? "analysis" : isAudioRun ? "audio" : "procurement";
    const runId = Number(payload.runId || 0);
    if (payload.running && runId && !state.activeRunIds[runKind]) {
      state.activeRunIds[runKind] = runId;
      if (runKind === "analysis") {
        updateAnalysisForm();
      }
    }
    const runMatchesUi = Boolean(runId && state.activeRunIds[runKind] === runId);
    const activeBar = isAnalysisRun ? analysisProgressBar : isAudioRun ? audioProgressBar : progressBar;
    const activeLabel = isAnalysisRun ? analysisProgressLabel : isAudioRun ? audioProgressLabel : progressLabel;
    if (payload.running) {
      const total = Number(progress.total || 0);
      const current = Number(progress.current || 0);
      const percent = total > 0 ? Math.max(3, Math.min(100, Math.round((current / total) * 100))) : 15;
      activeBar.style.width = `${percent}%`;
      activeLabel.textContent = total > 0 ? `${current}/${total} - ${progress.label || "Running"}` : progress.label || "Running";
      setStatus("Running");
    } else if (payload.status === "complete" && runMatchesUi && !state.handledRunIds.has(runId)) {
      state.handledRunIds.add(runId);
      activeBar.style.width = "100%";
      activeLabel.textContent = "Complete";
      setStatus("Complete");
      if (runKind === "procurement") {
        const plan = state.workflow.active ? state.workflow.plan : null;
        const destination = plan && !plan.processing && plan.analysis
          ? "Analysis"
          : plan && !plan.processing && !plan.analysis
            ? "workflow completion"
            : "Processing";
        procurementNextTitle.textContent = `Continue to ${destination}`;
        procurementNextCopy.textContent = `Procurement is complete. Continue to ${destination.toLowerCase()}.`;
        goToProcessingButton.textContent = destination === "workflow completion" ? "Finish workflow" : `Open ${destination.toLowerCase()}`;
        procurementNextStep.classList.remove("hidden");
      }
      if (runKind === "audio") {
        if (state.pendingAudioOutput) {
          state.workflow.imports.audio = state.pendingAudioOutput;
          state.pendingAudioOutput = "";
        }
        const continueToAnalysis = !state.workflow.active || Boolean(state.workflow.plan?.analysis);
        audioNextTitle.textContent = continueToAnalysis ? "Continue to Analysis" : "Finish workflow";
        audioNextCopy.textContent = continueToAnalysis
          ? "Audio outputs are ready. Continue to Analysis."
          : "Audio outputs are ready and every selected workflow stage is complete.";
        audioToAnalysisButton.textContent = continueToAnalysis ? "Open analysis" : "Finish workflow";
        audioNextStep.classList.remove("hidden");
      }
      if (runKind === "analysis" && state.workflow.active) {
        state.workflow.active = false;
        setStatus("Workflow complete");
      }
      if (runKind === "analysis") {
        state.activeRunIds.analysis = null;
        updateAnalysisForm();
      }
    } else if (["failed", "stopped"].includes(payload.status) && runMatchesUi) {
      if (runKind === "audio") {
        state.pendingAudioOutput = "";
        state.workflow.imports.audio = "";
      }
      const failureMessage = payload.status === "stopped" ? "Stopped." : analysisFailureMessage(progress);
      activeLabel.textContent = failureMessage;
      setStatus(payload.status === "stopped" ? "Stopped" : failureMessage);
      if (runKind === "analysis") {
        state.activeRunIds.analysis = null;
        updateAnalysisForm();
      }
    }
  } catch (error) {
    setStatus(error.message);
  }
}

async function pollStateLoop() {
  try {
    await pollState();
  } finally {
    if (!state.closing) {
      progressPollTimer = window.setTimeout(pollStateLoop, PROGRESS_POLL_INTERVAL_MS);
    }
  }
}

// Focus supports embedded YouTube for remote videos and local
// streaming for already-downloaded files. Segment times are saved the same way.
async function openSegmentDialog(video) {
  state.selectedVideo = video;
  state.selectedVideoId = video.id;
  state.selectedSegmentId = null;
  segmentDialogTitle.textContent = video.title || video.video_id || "Untitled video";
  segmentDialogMeta.textContent = `${video.speaker} / ${video.duration_display || secondsToClock(video.duration_seconds)} / ${video.license || "Unknown"}`;
  segmentStartInput.value = "0:00";
  const duration = getVideoDuration(video);
  segmentEndInput.value = formatEditableTimecode(duration > 0 ? duration : 30);
  await preparePlayer(video);
  updateSegmentDialog();
  if (!segmentDialog.open) {
    segmentDialog.showModal();
  }
}

async function preparePlayer(video) {
  stopCurrentPlayers();
  const hasLocalSource = ["folder", "file"].includes(String(video.source_kind || "").toLowerCase())
    && Boolean(video.source_path);
  if (!hasLocalSource && (video.video_id || video.youtube_url)) {
    manualPlayer.classList.add("hidden");
    youtubePlayer.classList.remove("hidden");
    loadYouTubeIframeAt(0);
    return;
  }
  youtubePlayer.classList.add("hidden");
  youtubePlayer.innerHTML = "";
  manualPlayer.classList.remove("hidden");
  manualPlayer.src = `/media?token=${encodeURIComponent(launcherToken)}&path=${encodeURIComponent(video.source_path)}`;
}

function stopCurrentPlayers() {
  stopPlaybackSync();
  youtubePlayer.innerHTML = "";
  manualPlayer.pause();
  manualPlayer.removeAttribute("src");
}

function getCurrentPlaybackTime() {
  if (!manualPlayer.classList.contains("hidden")) {
    return roundSecond(manualPlayer.currentTime || 0);
  }
  return 0;
}

function startPlaybackSync() {
  stopPlaybackSync();
  state.playerSyncTimer = window.setInterval(updatePlaybackPosition, 250);
  updatePlaybackPosition();
}

function stopPlaybackSync() {
  if (state.playerSyncTimer !== null) {
    window.clearInterval(state.playerSyncTimer);
    state.playerSyncTimer = null;
  }
}

function updatePlaybackPosition() {
  const duration = getVideoDuration(state.selectedVideo || {});
  const current = Math.min(duration || Number.POSITIVE_INFINITY, getCurrentPlaybackTime());
  renderPlaybackPosition(current, duration);
}

function renderPlaybackPosition(current, duration = getVideoDuration(state.selectedVideo || {})) {
  const left = duration > 0 ? Math.max(0, Math.min(100, (current / duration) * 100)) : 0;
  timelinePlayhead.style.left = `${left}%`;
  playbackTimeLabel.textContent = `${formatEditableTimecode(current)} / ${formatEditableTimecode(duration)}`;
  timeline.setAttribute("aria-valuemax", String(Math.max(0, duration)));
  timeline.setAttribute("aria-valuenow", String(Math.max(0, current)));
  timeline.setAttribute(
    "aria-valuetext",
    `${formatEditableTimecode(current)} of ${formatEditableTimecode(duration)}`,
  );
}

function seekPlayback(seconds) {
  const duration = getVideoDuration(state.selectedVideo || {});
  const target = Math.max(0, duration > 0 ? Math.min(duration, seconds) : seconds);
  if (!manualPlayer.classList.contains("hidden")) {
    manualPlayer.currentTime = target;
  } else if (!youtubePlayer.classList.contains("hidden")) {
    loadYouTubeIframeAt(target);
  }
  renderPlaybackPosition(target, duration);
}

function loadYouTubeIframeAt(seconds) {
  const video = state.selectedVideo || {};
  const videoId = video.video_id || youtubeIdFromUrl(video.youtube_url);
  if (!videoId) {
    return;
  }
  const start = Math.max(0, Math.floor(seconds));
  youtubePlayer.innerHTML = `<iframe title="YouTube video preview" src="https://www.youtube-nocookie.com/embed/${encodeURIComponent(videoId)}?rel=0&start=${start}" referrerpolicy="no-referrer" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>`;
}

function updateSegmentDialog() {
  renderTimeline();
  renderTicks();
  renderSegmentList();
  renderManualStats();
  renderManualList();
  updatePlaybackPosition();
}

function renderTicks() {
  tickLayer.innerHTML = "";
  const duration = getVideoDuration(state.selectedVideo || {});
  for (let index = 0; index < 5; index += 1) {
    const tick = document.createElement("span");
    tick.textContent = secondsToClock(duration * (index / 4));
    tickLayer.appendChild(tick);
  }
}

function renderTimeline(previewSegment = null) {
  segmentsLayer.innerHTML = "";
  previewLayer.innerHTML = "";
  const duration = getVideoDuration(state.selectedVideo || {});
  getSegments(state.selectedVideoId).forEach((segment) => {
    segmentsLayer.appendChild(createSegmentBlock(segment, duration, "segment-block"));
  });
  if (previewSegment) {
    previewLayer.appendChild(createSegmentBlock(previewSegment, duration, "preview-block"));
  }
}

function createSegmentBlock(segment, duration, className) {
  const interactive = className === "segment-block";
  const block = document.createElement("div");
  block.className = className;
  const left = duration > 0 ? (segment.start / duration) * 100 : 0;
  const width = duration > 0 ? ((segment.end - segment.start) / duration) * 100 : 0;
  block.style.left = `${left}%`;
  block.style.width = `${Math.max(width, 0.5)}%`;
  block.title = `${secondsToClock(segment.start)} to ${secondsToClock(segment.end)}`;
  if (interactive) {
    const selected = segment.id === state.selectedSegmentId;
    block.dataset.segmentId = segment.id;
    block.classList.toggle("selected", selected);
    block.setAttribute("role", "button");
    block.setAttribute("tabindex", "0");
    block.setAttribute("aria-pressed", String(selected));
    block.setAttribute("aria-label", `Select clip ${secondsToClock(segment.start)} to ${secondsToClock(segment.end)}`);
    block.addEventListener("pointerdown", (event) => event.stopPropagation());
    block.addEventListener("click", (event) => {
      event.stopPropagation();
      selectFocusSegment(segment.id);
    });
    block.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectFocusSegment(segment.id);
      } else if (event.key === "Delete" && segment.id === state.selectedSegmentId) {
        event.preventDefault();
        deleteSelectedSegment();
      }
    });
    ["start", "end"].forEach((edge) => {
      const handle = document.createElement("button");
      handle.type = "button";
      handle.className = `segment-resize-handle ${edge}`;
      handle.tabIndex = selected ? 0 : -1;
      handle.setAttribute("aria-label", `${edge === "start" ? "Adjust start" : "Adjust end"} of selected clip`);
      handle.addEventListener("pointerdown", (event) => beginSegmentResize(event, segment.id, edge));
      handle.addEventListener("click", (event) => event.stopPropagation());
      handle.addEventListener("keydown", (event) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") {
          return;
        }
        event.preventDefault();
        event.stopPropagation();
        nudgeSegmentEdge(segment.id, edge, event.key === "ArrowLeft" ? -1 : 1);
      });
      block.appendChild(handle);
    });
  }
  return block;
}

function getSelectedFocusSegment() {
  return getSegments(state.selectedVideoId).find((segment) => segment.id === state.selectedSegmentId) || null;
}

function selectFocusSegment(segmentId) {
  const segment = getSegments(state.selectedVideoId).find((item) => item.id === segmentId) || null;
  state.selectedSegmentId = segment ? segment.id : null;
  if (segment) {
    segmentStartInput.value = formatEditableTimecode(segment.start);
    segmentEndInput.value = formatEditableTimecode(segment.end);
  }
  renderTimeline();
  renderSegmentList();
  renderManualStats();
  document.querySelector(`[data-segment-row-id="${CSS.escape(segmentId || "")}"]`)?.scrollIntoView({ block: "nearest" });
}

function renderSegmentList() {
  segmentList.innerHTML = "";
  const segments = getSegments(state.selectedVideoId);
  if (!segments.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No segments selected for this video.";
    segmentList.appendChild(empty);
    return;
  }
  segments.forEach((segment, index) => {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "segment-row";
    row.dataset.segmentRowId = segment.id;
    row.classList.toggle("selected", segment.id === state.selectedSegmentId);
    row.setAttribute("aria-pressed", String(segment.id === state.selectedSegmentId));
    const details = document.createElement("div");
    details.innerHTML = `<strong>Segment ${index + 1}: ${secondsToClock(segment.start)} to ${secondsToClock(segment.end)}</strong><span>${(segment.end - segment.start).toFixed(1)} seconds</span>`;
    row.appendChild(details);
    row.addEventListener("click", () => selectFocusSegment(segment.id));
    segmentList.appendChild(row);
  });
}

function renderManualStats() {
  const duration = getVideoDuration(state.selectedVideo || {});
  const segments = getSegments(state.selectedVideoId);
  const selected = getSelectedFocusSegment();
  const selectedDuration = selected ? Math.max(0, selected.end - selected.start) : 0;
  const share = duration > 0 ? (selectedDuration / duration) * 100 : 0;
  manualTotal.textContent = selected ? `Selected clip: ${secondsToClock(selectedDuration)}` : "Selected clip: none";
  manualShare.textContent = `Clip share: ${share.toFixed(1)}%`;
  manualCount.textContent = `Segments: ${segments.length}`;
  deleteSegmentButton.disabled = !selected;
}

function deleteSelectedSegment() {
  const selected = getSelectedFocusSegment();
  if (!selected) {
    return;
  }
  setSegments(
    state.selectedVideoId,
    getSegments(state.selectedVideoId).filter((segment) => segment.id !== selected.id),
  );
  state.selectedSegmentId = null;
  setStatus("Selected segment deleted.");
  updateSegmentDialog();
}

function addManualSegment(startValue, endValue) {
  if (!state.selectedVideo) {
    setStatus("Select a video before adding segments.");
    return;
  }
  const duration = getVideoDuration(state.selectedVideo);
  const parsedStart = parseEditableTimecode(startValue);
  const parsedEnd = parseEditableTimecode(endValue);
  if (!Number.isFinite(parsedStart) || !Number.isFinite(parsedEnd)) {
    setStatus("Enter times as seconds, MM:SS, or HH:MM:SS.");
    return;
  }
  const start = snapFocusTime(Math.max(0, parsedStart));
  const end = Math.max(start, snapFocusTime(Math.max(start, parsedEnd)));
  const safeEnd = duration > 0 ? Math.min(end, duration) : end;
  if (safeEnd - start < 0.5) {
    setStatus("Segment must be at least half a second.");
    return;
  }
  const existingSegments = getSegments(state.selectedVideoId);
  if (existingSegments.some((segment) => start < segment.end && safeEnd > segment.start)) {
    setStatus("This Focus segment overlaps an existing selection.");
    return;
  }
  const added = {
    id: `focus-${state.nextSegmentId++}`,
    start: roundSecond(start),
    end: roundSecond(safeEnd),
  };
  const segments = [...existingSegments, added].sort((a, b) => a.start - b.start || a.end - b.end);
  setSegments(state.selectedVideoId, segments);
  state.selectedSegmentId = added.id;
  setStatus("Segment added.");
  updateSegmentDialog();
}

function focusSnapThresholdSeconds() {
  const duration = getVideoDuration(state.selectedVideo || {});
  const width = timeline.getBoundingClientRect().width;
  if (duration <= 0 || width <= 0) {
    return 0.5;
  }
  return Math.max(0.2, Math.min(2, duration * (10 / width)));
}

function snapFocusTime(value, { excludeSegmentId = null } = {}) {
  const duration = getVideoDuration(state.selectedVideo || {});
  const safeValue = Math.max(0, duration > 0 ? Math.min(duration, value) : value);
  const points = [0, duration, getCurrentPlaybackTime()];
  getSegments(state.selectedVideoId).forEach((segment) => {
    if (segment.id !== excludeSegmentId) {
      points.push(segment.start, segment.end);
    }
  });
  const threshold = focusSnapThresholdSeconds();
  const nearest = points
    .filter((point) => Number.isFinite(point))
    .map((point) => ({ point, distance: Math.abs(point - safeValue) }))
    .sort((a, b) => a.distance - b.distance)[0];
  return nearest && nearest.distance <= threshold ? roundSecond(nearest.point) : roundSecond(safeValue);
}

function timelineSeconds(event) {
  const duration = getVideoDuration(state.selectedVideo || {});
  const rect = timeline.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width));
  return roundSecond(ratio * duration);
}

function beginSegmentResize(event, segmentId, edge) {
  event.preventDefault();
  event.stopPropagation();
  if (getVideoDuration(state.selectedVideo || {}) <= 0) {
    setStatus("Wait for the video duration before resizing a segment.");
    return;
  }
  const original = getSegments(state.selectedVideoId).find((segment) => segment.id === segmentId);
  if (!original) {
    return;
  }
  timeline.setPointerCapture(event.pointerId);
  state.selectedSegmentId = segmentId;
  state.drag = {
    type: "resize",
    segmentId,
    edge,
    original: { ...original },
    preview: { ...original },
    pointerId: event.pointerId,
  };
  renderSegmentList();
  renderManualStats();
}

function resizedSegmentFromPointer(drag, value) {
  const segments = getSegments(state.selectedVideoId);
  const index = segments.findIndex((segment) => segment.id === drag.segmentId);
  if (index < 0) {
    return null;
  }
  const duration = getVideoDuration(state.selectedVideo || {});
  const snapped = snapFocusTime(value, { excludeSegmentId: drag.segmentId });
  const minimum = 0.5;
  if (drag.edge === "start") {
    const lowerBound = index > 0 ? segments[index - 1].end : 0;
    return {
      ...drag.original,
      start: roundSecond(Math.max(lowerBound, Math.min(snapped, drag.original.end - minimum))),
    };
  }
  const upperBound = index < segments.length - 1 ? segments[index + 1].start : duration;
  return {
    ...drag.original,
    end: roundSecond(
      Math.min(
        upperBound > 0 ? upperBound : Math.max(drag.original.end, snapped),
        Math.max(snapped, drag.original.start + minimum),
      ),
    ),
  };
}

function nudgeSegmentEdge(segmentId, edge, direction) {
  const original = getSegments(state.selectedVideoId).find((segment) => segment.id === segmentId);
  if (!original) {
    return;
  }
  const value = original[edge] + direction * 0.5;
  const resized = resizedSegmentFromPointer(
    {
      type: "resize",
      segmentId,
      edge,
      original: { ...original },
      preview: { ...original },
    },
    value,
  );
  if (!resized || resized.end - resized.start < 0.5) {
    return;
  }
  setSegments(
    state.selectedVideoId,
    getSegments(state.selectedVideoId).map((segment) => (segment.id === resized.id ? resized : segment)),
  );
  selectFocusSegment(resized.id);
  setStatus("Segment edge updated.");
}

function releaseFocusDrag() {
  const pointerId = state.drag && state.drag.pointerId;
  state.drag = null;
  if (pointerId !== undefined && timeline.hasPointerCapture(pointerId)) {
    timeline.releasePointerCapture(pointerId);
  }
  renderTimeline();
}

function cleanupSegmentDialog() {
  releaseFocusDrag();
  stopCurrentPlayers();
  youtubePlayer.classList.add("hidden");
  manualPlayer.classList.add("hidden");
}

// Dragging creates a Focus range. A click without a range seeks the player.
function segmentFromDrag(anchor, current) {
  const duration = getVideoDuration(state.selectedVideo || {});
  const snappedAnchor = snapFocusTime(anchor);
  const snappedCurrent = snapFocusTime(current);
  const start = Math.max(0, Math.min(snappedAnchor, snappedCurrent));
  const end = duration > 0 ? Math.min(duration, Math.max(snappedAnchor, snappedCurrent)) : Math.max(snappedAnchor, snappedCurrent);
  if (end - start < 0.5) {
    return null;
  }
  return { start: roundSecond(start), end: roundSecond(end) };
}

function youtubeIdFromUrl(url) {
  const match = String(url || "").match(/[?&]v=([A-Za-z0-9_-]{11})|youtu\.be\/([A-Za-z0-9_-]{11})|\/(?:shorts|embed|live)\/([A-Za-z0-9_-]{11})/);
  return match ? match[1] || match[2] || match[3] : "";
}

function roundSecond(value) {
  return Math.round(Number(value || 0) * 10) / 10;
}

function selectedMaxSegmentSeconds() {
  const value = Number(maxSegmentInput.value);
  if (!Number.isFinite(value) || value < 1 || value > 3600) {
    maxSegmentInput.value = "30";
    return 30;
  }
  return value;
}

function betaOnlyVideoIdList() {
  return betaOnlyVideoIdsInput.value
    .split(/[\\s,;]+/)
    .map((value) => value.trim())
    .filter(Boolean);
}

function betaRunVideoCount(mode) {
  if (mode === "manual") {
    return getSelectedSegmentCount();
  }
  if (mode !== "clean-speaker-beta") {
    return getSelectedVideos().length;
  }
  const selectedIds = betaOnlyVideoIdList();
  if (selectedIds.length) {
    const requested = new Set(selectedIds.map((value) => youtubeIdFromUrl(value) || value));
    const matchingCount = getSelectedVideos().filter((video) =>
      requested.has(video.video_id || youtubeIdFromUrl(video.youtube_url)),
    ).length;
    return betaRandomOneToggle.checked ? Math.min(1, matchingCount) : matchingCount;
  }
  const baseCount = betaRandomOneToggle.checked ? Math.min(1, getSelectedVideos().length) : getSelectedVideos().length;
  return Math.max(0, baseCount - (Number(betaSkipFirstInput.value) || 0));
}

function escapeHtml(value) {
  const div = document.createElement("div");
  div.textContent = value == null ? "" : String(value);
  return div.innerHTML;
}

// Event wiring lives at the end so the setup reads in the same order as the UI:
// stage navigation, browsing/running, Focus selection, then startup refresh.
stepButtons.forEach((button) =>
  button.addEventListener("click", () => {
    if (!button.disabled) {
      showScreen(button.dataset.screenTarget);
    }
  }),
);
openProcurementButton.addEventListener("click", showProcurement);
openProcessingButton.addEventListener("click", showProcessingHub);
openAnalysisButton.addEventListener("click", showAnalysis);
openSettingsButton.addEventListener("click", () => settingsDialog.showModal());
settingsDialog.addEventListener("cancel", resetRevokeConfirmation);
settingsDialog.addEventListener("close", resetRevokeConfirmation);
closeSettingsButton.addEventListener("click", () => {
  resetRevokeConfirmation();
  settingsDialog.close();
});
saveSettingsButton.addEventListener("click", () => persistSettingsForm().catch((error) => setStatus(error.message)));
revokeAccessButton.addEventListener("click", () => revokeAccess().catch((error) => setStatus(error.message)));
ramLimitModeSelect.addEventListener("change", updateRamLimitMode);
resourceLimitsEnabledToggle.addEventListener("change", updateResourceLimitState);
guidedWorkflowToggle.addEventListener("change", updateWorkflowPlanner);
startGuidedWorkflowButton.addEventListener("click", () => startGuidedWorkflow().catch((error) => setStatus(error.message)));
browseWorkflowFaceButton.addEventListener("click", () => browseInto("folder", workflowFaceImportPath).catch((error) => setStatus(error.message)));
browseWorkflowAudioButton.addEventListener("click", () => browseInto("folder", workflowAudioImportPath).catch((error) => setStatus(error.message)));
browseWorkflowTextButton.addEventListener("click", () => browseInto("folder", workflowTextImportPath).catch((error) => setStatus(error.message)));
backToModesButton.addEventListener("click", showModeHome);
goToProcessingButton.addEventListener("click", () => continueAfterProcurement().catch((error) => setStatus(error.message)));
openAudioProcessingButton.addEventListener("click", () => {
  showScreen("audio-input");
  updateAudioMode();
});
openFaceProcessingButton.addEventListener("click", () => setStatus("Face processing is import-only in this release."));
openTextProcessingButton.addEventListener("click", () => setStatus("Text processing is import-only in this release."));
browseFaceImportButton.addEventListener("click", () => browseInto("folder", faceImportPathInput).catch((error) => setStatus(error.message)));
browseAudioImportHubButton.addEventListener("click", () => browseInto("folder", audioImportHubPathInput).catch((error) => setStatus(error.message)));
browseTextImportButton.addEventListener("click", () => browseInto("folder", textImportPathInput).catch((error) => setStatus(error.message)));
continueToAnalysisButton.addEventListener("click", showAnalysis);
backToProcessingButton.addEventListener("click", showProcessingHub);
backToAudioInputButton.addEventListener("click", () => showScreen("audio-input"));
browseOutputButton.addEventListener("click", () => browse("output").catch((error) => setStatus(error.message)));
closeSourcePickerButton.addEventListener("click", () => {
  sourcePickerDialog.close();
  setStatus("Ready");
});
sourcePickerDialog.addEventListener("cancel", () => setStatus("Ready"));
chooseSourceFolderButton.addEventListener("click", () =>
  chooseProcurementSource("folder").catch((error) => setStatus(error.message)),
);
chooseSourceFileButton.addEventListener("click", () =>
  chooseProcurementSource("source-file").catch((error) => setStatus(error.message)),
);
audioModeInputs.forEach((input) => input.addEventListener("change", () => {
  updateAudioMode();
  loadAudioCatalogSelection().catch((error) => setStatus(error.message));
}));
audioImportToggle.addEventListener("change", updateAudioMode);
audioSourcePathInput.addEventListener("input", clearAudioCatalogSelection);
audioSourcePathInput.addEventListener("change", () => {
  loadAudioCatalogSelection().catch((error) => setStatus(error.message));
});
audioCatalogFilterField.addEventListener("change", renderAudioCatalogSelection);
audioCatalogFilterText.addEventListener("input", renderAudioCatalogSelection);
audioCatalogSortField.addEventListener("change", renderAudioCatalogSelection);
audioCatalogSortDirection.addEventListener("change", renderAudioCatalogSelection);
audioSelectVisibleSourcesButton.addEventListener("click", () => {
  state.audioSelectedSourceIds = setVisibleCatalogSelection(
    state.audioSelectedSourceIds,
    getVisibleAudioCatalogSources(),
    true,
  );
  renderAudioCatalogSelection();
});
audioClearVisibleSourcesButton.addEventListener("click", () => {
  state.audioSelectedSourceIds = setVisibleCatalogSelection(
    state.audioSelectedSourceIds,
    getVisibleAudioCatalogSources(),
    false,
  );
  renderAudioCatalogSelection();
});
browseAudioFolderButton.addEventListener("click", () => {
  clearAudioCatalogSelection();
  browseInto("folder", audioSourcePathInput)
    .then((selectedPath) => selectedPath && loadAudioCatalogSelection())
    .catch((error) => setStatus(error.message));
});
browseAudioVideoButton.addEventListener("click", () => {
  clearAudioCatalogSelection();
  browseInto("video", audioSourcePathInput).catch((error) => setStatus(error.message));
});
browseAudioOutputButton.addEventListener("click", () => browseInto("output", audioOutputRootInput).catch((error) => setStatus(error.message)));
runAudioButton.addEventListener("click", runAudioProcessing);
stopAudioButton.addEventListener("click", () => api("/api/stop", { method: "POST" }).catch((error) => setStatus(error.message)));
audioToAnalysisButton.addEventListener("click", () => continueAfterAudio().catch((error) => setStatus(error.message)));
analysisImplementedControls.forEach((controls) => {
  controls.enabled.addEventListener("change", updateAnalysisForm);
  controls.methodInputs.forEach((input) => input.addEventListener("change", updateAnalysisForm));
  controls.source.addEventListener("input", updateAnalysisForm);
  controls.browse.addEventListener("click", () => {
    browseInto("folder", controls.source)
      .then(updateAnalysisForm)
      .catch((error) => setStatus(error.message));
  });
});
discoverAnalysisSpeakersButton.addEventListener("click", discoverAnalysisSpeakers);
browseAnalysisSourceManifestButton.addEventListener("click", () => {
  browseInto("source-manifest", analysisSourceManifestInput)
    .then(updateAnalysisForm)
    .catch((error) => setStatus(error.message));
});
analysisSourceManifestInput.addEventListener("input", updateAnalysisForm);
addAnalysisSpeakerGroupButton.addEventListener("click", addAnalysisSpeakerGroup);
openAnalysisCustomizeButton.addEventListener("click", () => openAnalysisCustomization().catch((error) => setStatus(error.message)));
backFromAnalysisCustomizeButton.addEventListener("click", () => showScreen("analysis-input"));
saveAnalysisCustomizationButton.addEventListener("click", () => saveAnalysisCustomization().catch((error) => setStatus(error.message)));
analysisAutomaticGroupField.addEventListener("change", () => {
  if (!state.analysisProfileDraft) return;
  state.analysisProfileDraft.automaticGroupField = analysisAutomaticGroupField.value;
  renderAnalysisProfilePreview();
  announceAnalysisGroupWarnings();
  updateAnalysisForm();
});
analysisOutputRootInput.addEventListener("input", updateAnalysisForm);
analysisDefaultReferenceInput.addEventListener("input", updateAnalysisForm);
analysisReferenceOverridesInput.addEventListener("input", updateAnalysisForm);
analysisWriteCombinedToggle.addEventListener("change", updateAnalysisForm);
analysisConstructComparisonToggle.addEventListener("change", updateAnalysisForm);
analysisProbabilitySheetsToggle.addEventListener("change", updateAnalysisForm);
analysisConfidenceLevelInput.addEventListener("input", updateAnalysisForm);
analysisHeadlinePolicySelect.addEventListener("change", updateAnalysisForm);
browseAnalysisOutputButton.addEventListener("click", () => {
  browseInto("output", analysisOutputRootInput)
    .then(updateAnalysisForm)
    .catch((error) => setStatus(error.message));
});
runAnalysisButton.addEventListener("click", runAnalysis);
stopAnalysisButton.addEventListener("click", () => api("/api/stop", { method: "POST" }).catch((error) => setStatus(error.message)));
backToAnalysisInputButton.addEventListener("click", () => showScreen("analysis-input"));
scanButton.addEventListener("click", scan);
rescanButton.addEventListener("click", scan);
sourcePathInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    scan();
  }
});
sourcePathInput.addEventListener("input", () => {
  if (state.scan) {
    invalidateProcurementScan();
    setStatus("Source changed. Scan it again before running.");
  }
});
toRunButton.addEventListener("click", startSelectedMode);
runButton.addEventListener("click", startSelectedMode);
manualRunButton.addEventListener("click", () => runProcurement(createSegmentManifest()));
manualBackButton.addEventListener("click", () => showScreen("review"));
backToReviewButton.addEventListener("click", () => showScreen("review"));
stopButton.addEventListener("click", () => api("/api/stop", { method: "POST" }).catch((error) => setStatus(error.message)));
sortSelect.addEventListener("change", renderReview);
catalogFilterField.addEventListener("change", renderReview);
catalogFilterText.addEventListener("input", renderReview);
catalogSortField.addEventListener("change", renderReview);
catalogSortDirection.addEventListener("change", renderReview);
selectVisibleSourcesButton.addEventListener("click", () => {
  state.selectedSourceIds = setVisibleCatalogSelection(
    state.selectedSourceIds,
    getVisibleCatalogVideos(),
    true,
  );
  renderReview();
  updateMode();
});
clearVisibleSourcesButton.addEventListener("click", () => {
  state.selectedSourceIds = setVisibleCatalogSelection(
    state.selectedSourceIds,
    getVisibleCatalogVideos(),
    false,
  );
  renderReview();
  updateMode();
});
modeInputs.forEach((input) => input.addEventListener("change", updateMode));
betaOutputModeInputs.forEach((input) => input.addEventListener("change", updateBetaOutputMode));
toggleAllSpeakersButton.addEventListener("click", () => {
  const allSelected = state.scan && getSelectedSpeakers().length === state.scan.groups.length;
  setAllSpeakersSelected(!allSelected);
});
checkBetaReadinessButton.addEventListener("click", () => checkBetaReadiness().catch((error) => setStatus(error.message)));
closeSegmentDialogButton.addEventListener("click", () => segmentDialog.close());
segmentDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  segmentDialog.close();
});
segmentDialog.addEventListener("close", cleanupSegmentDialog);
useStartButton.addEventListener("click", () => {
  segmentStartInput.value = formatEditableTimecode(getCurrentPlaybackTime());
});
useEndButton.addEventListener("click", () => {
  segmentEndInput.value = formatEditableTimecode(getCurrentPlaybackTime());
});
addSegmentButton.addEventListener("click", () => addManualSegment(segmentStartInput.value, segmentEndInput.value));
deleteSegmentButton.addEventListener("click", deleteSelectedSegment);
[segmentStartInput, segmentEndInput].forEach((input) => {
  input.addEventListener("blur", () => {
    const parsed = parseEditableTimecode(input.value);
    if (Number.isFinite(parsed)) {
      input.value = formatEditableTimecode(parsed);
    }
  });
});
manualPlayer.addEventListener("loadedmetadata", () => {
  if (state.selectedVideo && !getVideoDuration(state.selectedVideo)) {
    state.selectedVideo.duration_seconds = manualPlayer.duration;
  }
  startPlaybackSync();
  updateSegmentDialog();
});
manualPlayer.addEventListener("timeupdate", updatePlaybackPosition);
timeline.addEventListener("pointerdown", (event) => {
  if (event.button !== 0 || !state.selectedVideo || getVideoDuration(state.selectedVideo) <= 0) {
    return;
  }
  timeline.setPointerCapture(event.pointerId);
  state.drag = {
    type: "create",
    anchor: snapFocusTime(timelineSeconds(event)),
    clientX: event.clientX,
    moved: false,
    pointerId: event.pointerId,
  };
});
timeline.addEventListener("pointermove", (event) => {
  if (!state.drag) {
    return;
  }
  if (state.drag.type === "resize") {
    state.drag.preview = resizedSegmentFromPointer(state.drag, timelineSeconds(event));
    renderTimeline(state.drag.preview);
    return;
  }
  state.drag.moved = state.drag.moved || Math.abs(event.clientX - state.drag.clientX) >= 4;
  renderTimeline(segmentFromDrag(state.drag.anchor, timelineSeconds(event)));
});
timeline.addEventListener("pointerup", (event) => {
  if (!state.drag) {
    return;
  }
  const drag = state.drag;
  const current = timelineSeconds(event);
  state.drag = null;
  renderTimeline();
  if (drag.type === "resize") {
    const resized = resizedSegmentFromPointer(drag, current) || drag.preview;
    if (resized) {
      setSegments(
        state.selectedVideoId,
        getSegments(state.selectedVideoId).map((segment) => (segment.id === resized.id ? resized : segment)),
      );
      selectFocusSegment(resized.id);
      setStatus("Segment edge updated.");
    }
    return;
  }
  const segment = drag.moved ? segmentFromDrag(drag.anchor, current) : null;
  if (segment) {
    segmentStartInput.value = formatEditableTimecode(segment.start);
    segmentEndInput.value = formatEditableTimecode(segment.end);
    addManualSegment(segment.start, segment.end);
  } else {
    seekPlayback(current);
  }
});
timeline.addEventListener("pointercancel", () => {
  releaseFocusDrag();
});
timeline.addEventListener("keydown", (event) => {
  const duration = getVideoDuration(state.selectedVideo || {});
  if (duration <= 0) {
    return;
  }
  const step = event.shiftKey ? 5 : 1;
  const current = getCurrentPlaybackTime();
  const targetByKey = {
    ArrowLeft: current - step,
    ArrowDown: current - step,
    ArrowRight: current + step,
    ArrowUp: current + step,
    Home: 0,
    End: duration,
  };
  if (!(event.key in targetByKey)) {
    return;
  }
  event.preventDefault();
  seekPlayback(targetByKey[event.key]);
});
timeline.addEventListener("lostpointercapture", () => {
  if (state.drag) {
    releaseFocusDrag();
  }
});

// Native WebView2 does not own Edge's F11 behavior, so route it through the
// pywebview bridge. Browser fallback retains the browser's normal shortcut.
document.addEventListener("keydown", (event) => {
  if (event.key !== "F11") {
    return;
  }
  const nativeToggle = window.pywebview?.api?.toggle_fullscreen;
  if (typeof nativeToggle !== "function") {
    return;
  }
  event.preventDefault();
  Promise.resolve(nativeToggle()).catch((error) => setStatus(`Full screen failed: ${error.message}`));
});

updateMode();
updateAudioMode();
renderAnalysisCustomization();
updateAnalysisForm();
updateWorkflowPlanner();
renderReview();
pollStateLoop();
