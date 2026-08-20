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
const discoverAnalysisSpeakersButton = document.querySelector("#discoverAnalysisSpeakersButton");
const analysisSpeakerDiscoveryStatus = document.querySelector("#analysisSpeakerDiscoveryStatus");
const analysisGroupWarningStatus = document.querySelector("#analysisGroupWarningStatus");
const analysisSpeakerGroups = document.querySelector("#analysisSpeakerGroups");
const addAnalysisSpeakerGroupButton = document.querySelector("#addAnalysisSpeakerGroupButton");
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
  if (groups.length > 4) {
    issues.push("The combined workbook supports at most four speaker groups.");
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
    if (group.speakerKeys.length > 3) {
      issues.push(`${displayName || `Group ${index + 1}`} may contain at most three speakers.`);
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

function analysisRunGateReasons({
  modalities,
  outputRoot,
  writeCombinedWorkbook,
  discoverySignature,
  currentSignature,
  speakers,
  groups,
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
    reasons.push("Discover speakers from the current modality sources.");
  }
  if (!speakers.length) {
    reasons.push("Discover at least one speaker for the combined workbook.");
  }
  reasons.push(...analysisSpeakerGroupIssues(speakers, groups));

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
    speakerGroups: writeCombinedWorkbook ? speakerGroups : [],
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

// Single source of truth for UI-only state. Backend state is still fetched from
// /api/state, but selections like the active speaker and segment list live here.
// The legacy "manual" mode value and DOM ids remain for saved-manifest compatibility;
// all user-facing copy calls this workflow Focus.
const state = {
  module: "home",
  scan: null,
  mode: "",
  audioMode: "batch",
  analysisSpeakers: [],
  analysisSpeakerGroups: [],
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
  state.analysisDiscoverySignature = "";
  state.nextAnalysisGroupId = 1;
  state.pendingAudioOutput = "";
  invalidateAnalysisAsyncOperation(state.analysisDiscoveryOperation);
  invalidateAnalysisAsyncOperation(state.analysisSubmissionOperation);
  analysisSpeakerDiscoveryStatus.textContent = "Choose source folders, then discover speakers.";
  renderAnalysisSpeakerGroups();
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
  return state.scan.groups.flatMap((group) => group.videos.map((video) => ({ ...video, speaker: group.speaker })));
}

function getSelectedSpeakers() {
  if (!state.scan) {
    return [];
  }
  return state.scan.groups
    .map((group) => group.speaker)
    .filter((speaker) => state.selectedSpeakers.has(speaker));
}

function getSelectedVideos() {
  const selected = state.selectedSpeakers;
  return getAllVideos().filter((video) => selected.has(video.speaker));
}

function setAllSpeakersSelected(selected) {
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
    tab.classList.toggle("excluded", !state.selectedSpeakers.has(group.speaker));

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selectedSpeakers.has(group.speaker);
    checkbox.setAttribute("aria-label", `Include ${group.speaker} in this run`);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) {
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
  videoGroups.appendChild(renderSpeakerGroup(group, sortVideos(group.videos), false));
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
  row.classList.toggle("selected", video.id === state.selectedVideoId);
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
  main.appendChild(meta);

  const side = document.createElement("div");
  if (manualList) {
    side.className = "segment-count";
    side.textContent = plural(getSegments(video.id).length, "segment");
  } else {
    side.className = "speaker-sub";
    side.textContent = video.youtube_url ? "YouTube link" : video.source_kind === "docx" ? "YouTube source" : "Local file";
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

function analysisModalitiesSignature(modalities = buildAnalysisModalities()) {
  return JSON.stringify(modalities);
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
    speakers: state.analysisSpeakers,
    groups: state.analysisSpeakerGroups,
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
    speakerGroups: buildAnalysisSpeakerGroups(),
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
    analysisSpeakerDiscoveryStatus.textContent = "Sources changed. Discover speakers again.";
    renderAnalysisSpeakerGroups();
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
  analysisLandmarksToggle.disabled = analysisLocked;
  analysisTimingToggle.disabled = analysisLocked;
  analysisExcludeGeometryToggle.disabled = analysisLocked;
  discoverAnalysisSpeakersButton.disabled = !combinedEnabled
    || !completeSources
    || state.analysisDiscoveryOperation.pending
    || analysisLocked;
  addAnalysisSpeakerGroupButton.disabled = !combinedEnabled
    || !state.analysisSpeakers.length
    || state.analysisSpeakerGroups.length >= 4
    || analysisLocked;
  analysisSpeakerGroups.querySelectorAll("input, button").forEach((control) => {
    control.disabled = !combinedEnabled || analysisLocked || control.dataset.assignmentLocked === "true";
  });

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
}

function createSensibleAnalysisGroups(speakers) {
  if (!speakers.length) {
    return [];
  }
  const groups = [];
  for (let index = 0; index < speakers.length; index += 3) {
    groups.push({
      id: `analysis-group-${state.nextAnalysisGroupId++}`,
      name: `Group ${groups.length + 1}`,
      speakerKeys: speakers.slice(index, index + 3).map((speaker) => speaker.key),
    });
  }
  return groups;
}

function speakerGroupAssignment(speakerKey) {
  return state.analysisSpeakerGroups.find((group) => group.speakerKeys.includes(speakerKey))?.id || "";
}

function analysisGroupContributionWarning(group) {
  const labels = { imotions: "Video / iMotions", audio: "Audio" };
  const deficits = buildAnalysisModalities()
    .filter((modality) => modality.name !== "text")
    .map((modality) => {
      const contributors = group.speakerKeys.filter((speakerKey) => {
        const speaker = state.analysisSpeakers.find((candidate) => candidate.key === speakerKey);
        return speaker && Array.isArray(speaker.availableIn) && speaker.availableIn.includes(modality.name);
      }).length;
      return contributors < 2 ? `${labels[modality.name]}: ${contributors}` : "";
    })
    .filter(Boolean);
  return deficits.length
    ? `Probability requires at least two contributing speakers per modality; fewer than two contributors were found (${deficits.join(", ")}).`
    : "";
}

function assignAnalysisSpeaker(groupId, speakerKey, selected) {
  const targetGroup = state.analysisSpeakerGroups.find((item) => item.id === groupId);
  if (
    selected
    && targetGroup
    && !targetGroup.speakerKeys.includes(speakerKey)
    && targetGroup.speakerKeys.length >= 3
  ) {
    setStatus(`${targetGroup.name} already contains the maximum of three speakers.`);
    renderAnalysisSpeakerGroups(`speaker:${groupId}:${speakerKey}`);
    updateAnalysisForm();
    return;
  }
  state.analysisSpeakerGroups.forEach((group) => {
    group.speakerKeys = group.speakerKeys.filter((key) => key !== speakerKey);
  });
  if (selected) {
    if (targetGroup) {
      targetGroup.speakerKeys.push(speakerKey);
    }
  }
  renderAnalysisSpeakerGroups(`speaker:${groupId}:${speakerKey}`);
  updateAnalysisForm();
}

function removeAnalysisSpeakerGroup(groupId) {
  const removedIndex = state.analysisSpeakerGroups.findIndex((group) => group.id === groupId);
  if (removedIndex < 0) {
    return;
  }
  state.analysisSpeakerGroups = state.analysisSpeakerGroups.filter((group) => group.id !== groupId);
  const adjacentGroup = state.analysisSpeakerGroups[Math.min(removedIndex, state.analysisSpeakerGroups.length - 1)];
  renderAnalysisSpeakerGroups(adjacentGroup ? `group-name:${adjacentGroup.id}` : "");
  updateAnalysisForm();
  if (!adjacentGroup) {
    addAnalysisSpeakerGroupButton.focus();
  }
}

function addAnalysisSpeakerGroup() {
  if (state.analysisSpeakerGroups.length >= 4) {
    setStatus("The combined workbook supports at most four speaker groups.");
    return;
  }
  const number = state.nextAnalysisGroupId++;
  const groupId = `analysis-group-${number}`;
  state.analysisSpeakerGroups.push({
    id: groupId,
    name: `Group ${state.analysisSpeakerGroups.length + 1}`,
    speakerKeys: [],
  });
  renderAnalysisSpeakerGroups(`group-name:${groupId}`);
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
  const warningText = state.analysisSpeakerGroups
    .map(analysisGroupContributionWarning)
    .filter(Boolean)
    .join(" ");
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
  if (!state.analysisSpeakers.length) {
    const empty = document.createElement("p");
    empty.className = "analysis-group-empty";
    empty.textContent = "No speakers discovered yet.";
    analysisSpeakerGroups.appendChild(empty);
    announceAnalysisGroupWarnings();
    return;
  }
  state.analysisSpeakerGroups.forEach((group, groupIndex) => {
    const row = document.createElement("section");
    row.className = "analysis-speaker-group";
    const warningId = `analysis-group-warning-${groupIndex + 1}`;
    row.setAttribute("aria-describedby", warningId);

    const header = document.createElement("div");
    header.className = "analysis-speaker-group-head";
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.value = group.name;
    nameInput.setAttribute("aria-label", "Speaker group name");
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
    state.analysisSpeakers.forEach((speaker) => {
      const assignment = speakerGroupAssignment(speaker.key);
      const label = document.createElement("label");
      label.className = "analysis-speaker-choice";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = assignment === group.id;
      checkbox.dataset.assignmentLocked = String(Boolean(assignment) && assignment !== group.id);
      checkbox.disabled = checkbox.dataset.assignmentLocked === "true";
      checkbox.setAttribute("aria-describedby", warningId);
      checkbox.setAttribute("data-analysis-speaker-name", speaker.name);
      checkbox.setAttribute("data-analysis-focus", `speaker:${group.id}:${speaker.key}`);
      checkbox.addEventListener("change", () => assignAnalysisSpeaker(group.id, speaker.key, checkbox.checked));
      const name = document.createElement("span");
      name.textContent = speaker.name;
      label.append(checkbox, name);
      choices.appendChild(label);
    });

    const warning = document.createElement("p");
    warning.className = "analysis-group-warning";
    warning.id = warningId;
    const warningText = analysisGroupContributionWarning(group);
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

async function discoverAnalysisSpeakers() {
  const modalities = buildAnalysisModalities();
  if (!hasCompleteAnalysisModality(modalities)) {
    setStatus("Complete at least one analysis source before discovering speakers.");
    return;
  }
  const signature = analysisModalitiesSignature(modalities);
  const token = beginAnalysisAsyncOperation(state.analysisDiscoveryOperation, signature);
  if (!token) {
    return;
  }
  analysisSpeakerDiscoveryStatus.textContent = "Discovering speakers...";
  updateAnalysisForm();
  try {
    const payload = await api("/api/analysis-speakers", {
      method: "POST",
      body: { modalities },
    });
    if (!isAnalysisAsyncOperationCurrent(
      state.analysisDiscoveryOperation,
      token,
      analysisModalitiesSignature(),
    )) {
      return;
    }
    const seen = new Set();
    state.analysisSpeakers = (payload.speakers || []).filter((speaker) => {
      const valid = speaker && typeof speaker.key === "string" && typeof speaker.name === "string"
        && speaker.key.trim() && speaker.name.trim() && !seen.has(speaker.key);
      if (valid) {
        seen.add(speaker.key);
      }
      return valid;
    });
    state.analysisSpeakerGroups = createSensibleAnalysisGroups(state.analysisSpeakers);
    state.analysisDiscoverySignature = signature;
    const warnings = Array.isArray(payload.warnings) ? payload.warnings.filter(Boolean) : [];
    analysisSpeakerDiscoveryStatus.textContent = warnings.length
      ? `${state.analysisSpeakers.length} speakers found. ${warnings.join(" ")}`
      : `${state.analysisSpeakers.length} speakers found.`;
    renderAnalysisSpeakerGroups();
    setStatus("Speaker groups ready for review");
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
    renderAnalysisSpeakerGroups();
    analysisSpeakerDiscoveryStatus.textContent = error.message;
    setStatus(error.message);
  } finally {
    if (finishAnalysisAsyncOperation(state.analysisDiscoveryOperation, token)) {
      updateAnalysisForm();
    }
  }
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
  const speakerGroups = writeCombinedWorkbook ? buildAnalysisSpeakerGroups() : [];
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
      speakerGroups,
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
        video_id: video.video_id || null,
        video_title: video.title || null,
        speaker: video.speaker,
        source_path: video.source_path,
        source_kind: video.source_kind,
        youtube_url: video.youtube_url || null,
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
audioModeInputs.forEach((input) => input.addEventListener("change", updateAudioMode));
audioImportToggle.addEventListener("change", updateAudioMode);
browseAudioFolderButton.addEventListener("click", () => browseInto("folder", audioSourcePathInput).catch((error) => setStatus(error.message)));
browseAudioVideoButton.addEventListener("click", () => browseInto("video", audioSourcePathInput).catch((error) => setStatus(error.message)));
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
addAnalysisSpeakerGroupButton.addEventListener("click", addAnalysisSpeakerGroup);
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
renderAnalysisSpeakerGroups();
updateAnalysisForm();
updateWorkflowPlanner();
renderReview();
pollStateLoop();
