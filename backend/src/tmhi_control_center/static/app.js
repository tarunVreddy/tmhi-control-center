const THEME_STORAGE_KEY = "tmhi-control-center-theme";
const VIEW_STORAGE_KEY = "tmhi-control-center-view";
const DEFAULT_VIEW = "dashboard";
const AIM_POLL_INTERVAL_MS = 2000;
const AIM_MAX_CONSECUTIVE_ERRORS = 5;
const DEFAULT_MAP_CENTER = { latitude: 39.8283, longitude: -98.5795 };
const DEFAULT_MAP_RADIUS_KM = 0.8;
const MAP_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const LIVE_POLL_INTERVAL_MS = 60000;
// The build this page was served as; the server stamps it into the markup.
const PAGE_BUILD = document.querySelector('meta[name="tmhi-build"]')?.content || "";
const SPEED_TEST_PROFILE_BYTES = {
  gentle: 12_000_000,
  standard: 30_000_000,
  accurate: 125_000_000,
  extended: 300_000_000,
  maximum: 1_000_000_000,
};

// The history window has to be at least as wide as the gap between runs or the
// chart reads empty while the schedule is working normally. Daily cadence
// rotates across dayparts, so consecutive runs can sit 30 hours apart and a 24h
// window misses them for part of every cycle.
const SPEED_TEST_DEFAULT_RANGE = {
  disabled: "7",
  every_5_minutes: "1",
  every_10_minutes: "1",
  every_15_minutes: "1",
  every_30_minutes: "1",
  hourly: "1",
  daily: "7",
  weekly: "30",
  monthly: "all",
};
const SPEED_TEST_RUNS_PER_DAY = {
  disabled: 0,
  every_5_minutes: 288,
  every_10_minutes: 144,
  every_15_minutes: 96,
  every_30_minutes: 48,
  hourly: 24,
  every_6_hours: 4,
  every_12_hours: 2,
  daily: 1,
  weekly: 1 / 7,
  monthly: 1 / 30,
};

const state = {
  aimTimer: null,
  aimPaused: false,
  aimSnapshot: null,
  aimTrend: {},
  aimErrors: 0,
  config: null,
  status: null,
  overview: null,
  wifi: null,
  clients: null,
  events: [],
  firmwareBackups: null,
  rootResearch: null,
  rootResearchAssessment: null,
  mapData: null,
  telemetryHistory: null,
  telemetryHours: 6,
  connectionHistory: null,
  connectionDays: 14,
  timelineSelectedKey: null,
  timelineHidden: new Set(),
  timelineVisible: [],
  timelineRange: null,
  timelineDragging: false,
  updateReady: false,
  updateBuild: null,
  updateChecking: false,
  gatewayDetails: null,
  speedTestStatus: null,
  speedTestHistory: null,
  speedTestDays: 1,
  speedTestRange: "1",
  speedTestRangePinned: false,
  speedTestBusy: false,
  activeView: DEFAULT_VIEW,
  theme: "light",
  refreshing: false,
  liveRefreshing: false,
  lastLiveRefreshAt: 0,
  mapBusy: false,
  actionBusy: false,
  gatewayLoginBusy: false,
  snapshotBusy: false,
  seriesRunning: false,
  seriesAbort: false,
  maps: {
    preview: null,
    main: null,
    previewLayer: null,
    mainLayer: null,
  },
};

const ids = [
  "actionMessage",
  "aimHeading",
  "aimMeter",
  "aimMeterLabel",
  "aimMeterValue",
  "aimMetrics",
  "aimResetButton",
  "aimStateTag",
  "aimStatusMessage",
  "aimSummary",
  "aimToggleButton",
  "aimTrend",
  "aimUpdatedTag",
  "advancedCellTag",
  "advancedLabEnabled",
  "advancedModemAcknowledge",
  "advancedModemStatus",
  "advancedRadioProfile",
  "advancedUploadProfile",
  "checkButton",
  "clearOpenCellIdButton",
  "clientCountTag",
  "clientTableBody",
  "connectedDetail",
  "connectionChangeCount",
  "connectionChangeDetail",
  "connectionTimeline",
  "connectedMetric",
  "connectionDetails",
  "cqiTrendChart",
  "darkModeToggle",
  "dashboardMapPreview",
  "dashboardNextAction",
  "dashboardReadinessTag",
  "dashboardSetupList",
  "deviceDetails",
  "downloadSnapshotButton",
  "dryRunMetric",
  "dryRunToggle",
  "errorBanner",
  "eventsList",
  "forceReboot",
  "forgetGatewayButton",
  "firmwareBackupButton",
  "firmwareBackupList",
  "firmwareBackupSha256",
  "firmwareBackupStatus",
  "firmwareBackupVerified",
  "firmwareConsentPhrase",
  "firmwareFlashButton",
  "firmwareLabStatus",
  "firmwareRecoveryVerified",
  "firmwareSha256",
  "firmwareUnderstandsRisk",
  "gatewayButton",
  "gatewayDetail",
  "gatewayIdentity",
  "gatewayLoginState",
  "gatewayMetric",
  "gatewayPassword",
  "gatewayReachTag",
  "gatewaySections",
  "gatewaySubtitle",
  "homelabPlaybook",
  "homelabReadinessTag",
  "homelabScore",
  "homelabSetupList",
  "homelabSignalCoach",
  "homelabSummary",
  "internetDetail",
  "internetMetric",
  "lastCheckMetric",
  "lastOnlineMetric",
  "lastRefresh",
  "lookupClientsButton",
  "mapLatitude",
  "mapLongitude",
  "mapPreviewDetails",
  "mapPreviewTag",
  "mapProviderTag",
  "mapRadius",
  "mapRefreshButton",
  "mapStatusMessage",
  "mapTowerLockTag",
  "nearbyTowerCountTag",
  "nearbyTowerTableBody",
  "openCellIdKey",
  "outageBreakdown",
  "outageCount",
  "outageCountDetail",
  "outageDiagnosis",
  "outageHourChart",
  "outageHourZone",
  "outageMedian",
  "outageMedianDetail",
  "probeDetail",
  "probeMetric",
  "probeTableBody",
  "radioCards",
  "radioModeDetail",
  "radioModeMetric",
  "rebootButton",
  "rebootMetric",
  "refreshButton",
  "refreshClientsButton",
  "restartCount",
  "restartDetail",
  "rememberPassword",
  "saveAdvancedModemButton",
  "saveGatewayButton",
  "saveMapCenterButton",
  "saveOpenCellIdButton",
  "saveSettingsButton",
  "saveWifiButton",
  "seriesCount",
  "seriesInterval",
  "seriesStartButton",
  "seriesStopButton",
  "seriesTableBody",
  "signalMeter",
  "signalMeterLabel",
  "signalMeterValue",
  "signalMetrics",
  "signalQuality",
  "signalScore",
  "signalStateTag",
  "signalSummary",
  "sinrTrendChart",
  "skipStockBackupReminder",
  "stabilityCurrentLabel",
  "stabilityTag",
  "speedTestCadence",
  "speedTestConnections",
  "speedTestDataDetail",
  "speedTestDataUsed",
  "speedTestDayparts",
  "speedTestDownload",
  "speedTestDownloadDetail",
  "speedTestHistoryTag",
  "speedTestLatency",
  "speedTestLatencyDetail",
  "speedTestNextRun",
  "speedTestProfileLabel",
  "speedTestProfile",
  "speedTestRetention",
  "speedTestRunButton",
  "speedTestSaveButton",
  "speedTestScheduleDetail",
  "speedTestTrendChart",
  "speedTestUpload",
  "speedTestUploadDetail",
  "speedTestUsageEstimate",
  "speedTestUsageWarning",
  "rsrpTrendChart",
  "rootAcceptsBrickRisk",
  "rootAssessButton",
  "rootAssessmentStatus",
  "rootBootLogCaptured",
  "rootConsentPhrase",
  "rootFullBackupVerified",
  "rootHardStopList",
  "rootNotLeased",
  "rootOfflineRecoveryVerified",
  "rootOwnsHardware",
  "rootResearchFinding",
  "rootResearchPhases",
  "rootResearchTag",
  "rootRevisionRecorded",
  "rootSpareUnit",
  "rootUartVoltageVerified",
  "rootUnverifiedList",
  "rootVerifiedEvidenceList",
  "telemetryFreshness",
  "telemetryHistoryTag",
  "telemetryTrendGrid",
  "temperatureDetail",
  "temperatureMetric",
  "temperatureMetricCard",
  "temperatureTrendChart",
  "temperatureTrendPanel",
  "updateButton",
  "timelineDetail",
  "timelineFilters",
  "testFrequency",
  "themeModeLabel",
  "towerMap",
  "towerIdentityDetails",
  "uptimeDetail",
  "uptimeMetric",
  "useBrowserLocationButton",
  "useGatewayLocationButton",
  "watchdogMetric",
  "watchdogPhaseTag",
  "wifiDetails",
  "wifiRadioToggle",
  "wifiSsid",
];

const els = {};

const detailLabels = {
  api: "API",
  api_version: "API version",
  apn: "APN",
  architecture: "5G type",
  band: "Band",
  broadcast_enabled: "SSID broadcast",
  controller: "USB controller",
  data_port: "Gateway port",
  cell_id: "Cell ID",
  channel_2g: "2.4 GHz channel",
  channel_5g: "5 GHz channel",
  clients: "Connected clients",
  band_lock: "Band lock",
  cell_lock: "Tower lock",
  cell_scan: "Cell scan",
  custom_firmware_flash: "Custom flash",
  firmware: "Firmware",
  gateway_clock: "Gateway clock",
  hardware: "Hardware",
  iccid: "ICCID",
  imei: "IMEI",
  imsi: "IMSI",
  ipv6: "IPv6",
  ethernet_target: "Ethernet target",
  lac: "TAC/LAC",
  manufacturer: "Manufacturer",
  mcc: "MCC",
  mnc: "MNC",
  model: "Model",
  name: "Name",
  network_type: "Network",
  mode: "Radio mode",
  operator: "Operator",
  pci: "PCI",
  phone_number: "Phone number",
  plmn: "PLMN",
  preferred_chipset: "Preferred chipset",
  preferred_driver: "Preferred driver",
  radio: "Radio",
  radio_enabled: "Gateway Wi-Fi radios",
  radio_profile: "G4AR radio profile",
  radio_mode_override: "Radio override",
  root_access: "Root access",
  registration: "Registration",
  roaming: "Roaming",
  serial: "Serial",
  sim_status: "SIM",
  lte_anchor_override: "LTE anchor / NSA",
  stock_firmware_backup: "Recovery bundle",
  stock_backup_skipped: "Backup reminder",
  stock_support: "Stock firmware",
  ssid: "SSID",
  ssid_2g: "2.4 GHz SSID",
  ssid_5g: "5 GHz SSID",
  state: "Connection",
  support: "Support",
  tower_accuracy: "Tower accuracy",
  tower_distance: "Tower distance",
  tower_match: "Tower match",
  tower_match_note: "Match note",
  tx_power: "Transmit power",
  usb_ceiling: "USB ceiling",
  usb_ethernet_bridge: "USB Ethernet bridge",
  usb_hardware_probe: "USB hardware probe",
  upload_priority_qos: "Upload priority",
  uptime: "Uptime",
  wan_ipv4: "WAN IPv4",
  wan_ipv6: "WAN IPv6",
};

document.addEventListener("DOMContentLoaded", () => {
  for (const id of ids) {
    els[id] = document.getElementById(id);
  }

  initializeTheme();
  bindControls();
  activateView(window.localStorage.getItem(VIEW_STORAGE_KEY) || DEFAULT_VIEW, {
    refreshMap: false,
  });
  selectTab("probes");
  refreshAll();
  window.setInterval(refreshLiveData, LIVE_POLL_INTERVAL_MS);
  // iOS resumes a home-screen app where it left off instead of reloading it,
  // so coming back to the foreground is when a deploy gets noticed.
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) {
      checkForUpdate({ reloadWhenSafe: true });
    }
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      checkForUpdate({ reloadWhenSafe: true });
    }
    // Drop the aiming timer while hidden rather than waking every 2s to return
    // early, and pick it back up on return unless the pause was deliberate.
    if (document.hidden) {
      stopAiming();
    } else if (state.activeView === "aim" && !state.aimPaused) {
      startAiming();
    }
    if (!document.hidden && Date.now() - state.lastLiveRefreshAt >= LIVE_POLL_INTERVAL_MS) {
      refreshLiveData();
    }
  });
});

function bindControls() {
  els.refreshButton.addEventListener("click", () => refreshAll());
  els.checkButton.addEventListener("click", runCheck);
  els.gatewayButton.addEventListener("click", runGatewayTest);
  els.saveGatewayButton.addEventListener("click", saveGatewayLogin);
  els.forgetGatewayButton.addEventListener("click", clearGatewayLogin);
  els.saveWifiButton.addEventListener("click", saveWifiSettings);
  els.mapRefreshButton.addEventListener("click", () => refreshTowerMap({ includeNearby: true }));
  els.useBrowserLocationButton.addEventListener("click", useBrowserLocation);
  els.useGatewayLocationButton.addEventListener("click", useGatewayLocation);
  els.saveMapCenterButton.addEventListener("click", saveMapCenter);
  els.saveOpenCellIdButton.addEventListener("click", saveOpenCellIdKey);
  els.clearOpenCellIdButton.addEventListener("click", clearOpenCellIdKey);
  els.refreshClientsButton.addEventListener("click", () => refreshClients(false));
  els.lookupClientsButton.addEventListener("click", () => refreshClients(true));
  els.saveAdvancedModemButton.addEventListener("click", saveAdvancedModemSettings);
  els.firmwareBackupButton.addEventListener("click", createG4ARFirmwareBackup);
  els.firmwareFlashButton.addEventListener("click", armG4ARFlashGate);
  els.rootAssessButton.addEventListener("click", assessG4ARRootReadiness);
  els.downloadSnapshotButton.addEventListener("click", downloadSnapshot);
  els.saveSettingsButton.addEventListener("click", saveSettings);
  els.speedTestRunButton.addEventListener("click", runSpeedTestNow);
  els.speedTestSaveButton.addEventListener("click", saveSpeedTestSchedule);
  els.speedTestCadence.addEventListener("change", renderSpeedTestSchedulePreview);
  els.speedTestProfile.addEventListener("change", renderSpeedTestSchedulePreview);
  els.rebootButton.addEventListener("click", requestReboot);
  els.seriesStartButton.addEventListener("click", startSweep);
  els.seriesStopButton.addEventListener("click", stopSweep);
  els.gatewayPassword.addEventListener("input", updateControlState);
  els.wifiSsid.addEventListener("input", updateControlState);
  els.openCellIdKey.addEventListener("input", updateControlState);
  els.mapLatitude.addEventListener("input", updateControlState);
  els.mapLongitude.addEventListener("input", updateControlState);
  els.mapRadius.addEventListener("input", updateControlState);
  els.advancedLabEnabled.addEventListener("change", updateControlState);
  els.advancedModemAcknowledge.addEventListener("change", updateControlState);
  els.advancedUploadProfile.addEventListener("change", updateControlState);
  els.advancedRadioProfile.addEventListener("change", updateControlState);
  els.skipStockBackupReminder.addEventListener("change", updateControlState);
  els.firmwareBackupSha256.addEventListener("input", updateControlState);
  els.firmwareSha256.addEventListener("input", updateControlState);
  els.firmwareConsentPhrase.addEventListener("input", updateControlState);
  els.firmwareBackupVerified.addEventListener("change", updateControlState);
  els.firmwareRecoveryVerified.addEventListener("change", updateControlState);
  els.firmwareUnderstandsRisk.addEventListener("change", updateControlState);
  [
    els.rootOwnsHardware,
    els.rootNotLeased,
    els.rootSpareUnit,
    els.rootRevisionRecorded,
    els.rootUartVoltageVerified,
    els.rootBootLogCaptured,
    els.rootFullBackupVerified,
    els.rootOfflineRecoveryVerified,
    els.rootAcceptsBrickRisk,
  ].forEach((input) => input.addEventListener("change", updateControlState));
  els.rootConsentPhrase.addEventListener("input", updateControlState);
  els.darkModeToggle.addEventListener("change", () => {
    setTheme(els.darkModeToggle.checked ? "dark" : "light", { persist: true });
  });

  // A view switch starts at the top of the new view; otherwise the phone tab
  // bar leaves the reader partway down a page they have not seen.
  const openView = (view) => {
    const changed = view !== state.activeView;
    if (
      changed &&
      state.updateReady &&
      canReloadForUpdate() &&
      !alreadyReloadedFor(state.updateBuild)
    ) {
      // A deliberate move is a natural moment to pick up a waiting update;
      // the chosen view is remembered across the reload.
      selectView(view);
      reloadForUpdate();
      return;
    }
    activateView(view);
    if (changed) {
      window.scrollTo({ top: 0 });
    }
  };
  document.querySelectorAll("[data-view]").forEach((button) => {
    button.addEventListener("click", () => openView(button.dataset.view));
    button.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") {
        return;
      }
      event.preventDefault();
      openView(button.dataset.view);
    });
  });
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => selectTab(button.dataset.tab));
  });
  document.querySelectorAll("[data-telemetry-hours]").forEach((button) => {
    button.addEventListener("click", () => {
      const hours = Number(button.dataset.telemetryHours);
      if (Number.isFinite(hours)) {
        refreshTelemetryHistory(hours);
      }
    });
  });
  document.querySelectorAll("[data-stability-days]").forEach((button) => {
    button.addEventListener("click", () => {
      const days = Number(button.dataset.stabilityDays);
      if (Number.isFinite(days)) {
        refreshConnectionHistory(days);
      }
    });
  });
  document.querySelectorAll("[data-speedtest-days]").forEach((button) => {
    button.addEventListener("click", () => {
      const range = button.dataset.speedtestDays;
      const days = speedTestRangeToDays(range);
      if (Number.isFinite(days)) {
        state.speedTestRangePinned = true;
        refreshSpeedTestHistory(days, range);
      }
    });
  });

  els.aimToggleButton.addEventListener("click", toggleAiming);
  els.aimResetButton.addEventListener("click", resetAimSession);
  bindTimeline();
  els.updateButton.addEventListener("click", reloadForUpdate);
}

function initializeTheme() {
  const storedTheme = window.localStorage.getItem(THEME_STORAGE_KEY);
  const prefersDark = window.matchMedia?.("(prefers-color-scheme: dark)").matches;
  setTheme(storedTheme || (prefersDark ? "dark" : "light"), { persist: false });
}

function setTheme(theme, { persist = false } = {}) {
  state.theme = theme === "dark" ? "dark" : "light";
  document.documentElement.dataset.theme = state.theme;
  document.documentElement.style.colorScheme = state.theme;
  if (els.darkModeToggle) {
    els.darkModeToggle.checked = state.theme === "dark";
  }
  if (els.themeModeLabel) {
    setText(els.themeModeLabel, state.theme === "dark" ? "Dark mode" : "Light mode");
  }
  if (persist) {
    window.localStorage.setItem(THEME_STORAGE_KEY, state.theme);
  }
}

function selectView(name) {
  const requestedView = String(name || DEFAULT_VIEW);
  const availableViews = new Set(
    Array.from(document.querySelectorAll("[data-view-panel]")).map((panel) => panel.dataset.viewPanel)
  );
  state.activeView = availableViews.has(requestedView) ? requestedView : DEFAULT_VIEW;
  document.querySelectorAll(".nav-item[data-view]").forEach((button) => {
    const active = button.dataset.view === state.activeView;
    button.classList.toggle("is-active", active);
    if (active) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });
  document.querySelectorAll("[data-view-panel]").forEach((panel) => {
    panel.classList.toggle("is-active", panel.dataset.viewPanel === state.activeView);
  });
  window.localStorage.setItem(VIEW_STORAGE_KEY, state.activeView);
}

function activateView(name, { refreshMap = true } = {}) {
  selectView(name);
  // Only poll while the view is on screen; nothing else needs a 2s cadence.
  // An explicit Stop is respected until the button is used again.
  if (state.activeView === "aim" && !state.aimPaused) {
    startAiming();
  } else {
    stopAiming();
  }
  if (state.activeView === "map") {
    scheduleMainMapRender();
    if (refreshMap) {
      window.setTimeout(() => {
        refreshTowerMap({ includeNearby: true, quiet: true });
      }, 80);
    }
  }
}

async function refreshAll({ quiet = false } = {}) {
  if (state.refreshing) {
    return;
  }
  state.refreshing = true;
  updateControlState();
  if (!quiet) {
    hideError();
  }

  const results = await Promise.allSettled([
    api("/api/config"),
    api("/api/status"),
    api("/api/gateway/overview"),
    api("/api/gateway/wifi"),
    api("/api/gateway/clients"),
    api("/api/gateway/map?include_nearby=false"),
    api("/api/events?limit=10"),
    api("/api/g4ar/firmware/backups"),
    api(`/api/gateway/telemetry/history?hours=${state.telemetryHours}`),
    api("/api/speedtest/status"),
    api(`/api/speedtest/history?days=${state.speedTestDays}`),
    api("/api/g4ar/root/status"),
    api(`/api/connection/history?days=${state.connectionDays}`),
    api("/api/gateway/details"),
  ]);

  const errors = [];
  if (results[0].status === "fulfilled") {
    state.config = results[0].value;
  } else {
    errors.push(`Config: ${results[0].reason.message}`);
  }
  if (results[1].status === "fulfilled") {
    state.status = results[1].value;
  } else {
    errors.push(`Status: ${results[1].reason.message}`);
  }
  if (results[2].status === "fulfilled") {
    state.overview = results[2].value;
  } else {
    errors.push(`Gateway: ${results[2].reason.message}`);
  }
  if (results[3].status === "fulfilled") {
    state.wifi = results[3].value;
  } else {
    errors.push(`Wi-Fi: ${results[3].reason.message}`);
  }
  if (results[4].status === "fulfilled") {
    state.clients = results[4].value;
  } else {
    errors.push(`Clients: ${results[4].reason.message}`);
  }
  if (results[5].status === "fulfilled") {
    state.mapData = results[5].value;
  } else {
    errors.push(`Map: ${results[5].reason.message}`);
  }
  if (results[6].status === "fulfilled") {
    state.events = results[6].value;
  } else {
    errors.push(`Events: ${results[6].reason.message}`);
  }
  if (results[7].status === "fulfilled") {
    state.firmwareBackups = results[7].value;
  } else {
    errors.push(`Backups: ${results[7].reason.message}`);
  }
  if (results[8].status === "fulfilled") {
    state.telemetryHistory = results[8].value;
  } else {
    errors.push(`History: ${results[8].reason.message}`);
  }
  if (results[9].status === "fulfilled") {
    state.speedTestStatus = results[9].value;
  } else {
    errors.push(`Speed schedule: ${results[9].reason.message}`);
  }
  if (results[10].status === "fulfilled") {
    state.speedTestHistory = results[10].value;
  } else {
    errors.push(`Speed history: ${results[10].reason.message}`);
  }
  if (results[11].status === "fulfilled") {
    state.rootResearch = results[11].value;
  } else {
    errors.push(`Root research: ${results[11].reason.message}`);
  }
  if (results[12].status === "fulfilled") {
    state.connectionHistory = results[12].value;
  } else {
    errors.push(`Connection history: ${results[12].reason.message}`);
  }
  // Device details need a gateway login; without one the card falls back to
  // the overview's device block, so a failure here is not worth a banner.
  state.gatewayDetails = results[13].status === "fulfilled" ? results[13].value : null;

  await applySpeedTestDefaultRange();

  renderAll();
  setText(els.lastRefresh, `Updated ${formatTime(new Date())}`);
  if (errors.length) {
    showError(errors.join(" | "));
  }
  state.refreshing = false;
  state.lastLiveRefreshAt = Date.now();
  updateControlState();
}

async function refreshLiveData() {
  if (
    document.hidden ||
    state.refreshing ||
    state.liveRefreshing ||
    state.actionBusy ||
    state.mapBusy ||
    state.seriesRunning
  ) {
    return;
  }

  state.liveRefreshing = true;
  const [statusResult, overviewResult, historyResult, connectionResult] = await Promise.allSettled([
    api("/api/status"),
    api("/api/gateway/overview"),
    api(`/api/gateway/telemetry/history?hours=${state.telemetryHours}`),
    api(`/api/connection/history?days=${state.connectionDays}`),
  ]);
  if (statusResult.status === "fulfilled") {
    state.status = statusResult.value;
  }
  if (overviewResult.status === "fulfilled") {
    state.overview = overviewResult.value;
  }
  if (historyResult.status === "fulfilled") {
    state.telemetryHistory = historyResult.value;
  }
  if (connectionResult.status === "fulfilled") {
    state.connectionHistory = connectionResult.value;
  }

  renderHeader();
  renderOverviewMetrics();
  renderRadioStack();
  renderSignal();
  renderTelemetryTrends();
  renderConnectionStability();
  renderDetails();
  setText(els.lastRefresh, `Live ${formatTime(new Date())}`);
  state.lastLiveRefreshAt = Date.now();
  state.liveRefreshing = false;
  // On screen, only offer the update; reloading under someone is worse.
  checkForUpdate();
}

async function checkForUpdate({ reloadWhenSafe = false } = {}) {
  if (!PAGE_BUILD || PAGE_BUILD === "dev" || state.updateChecking) {
    return;
  }
  if (!state.updateReady) {
    state.updateChecking = true;
    try {
      const info = await api("/api/version");
      state.updateReady = Boolean(info?.build) && info.build !== PAGE_BUILD;
      state.updateBuild = info?.build || null;
    } catch {
      // Offline, or the server is mid-restart; the next check will tell.
    } finally {
      state.updateChecking = false;
    }
  }
  if (!state.updateReady) {
    return;
  }
  if (reloadWhenSafe && canReloadForUpdate() && !alreadyReloadedFor(state.updateBuild)) {
    reloadForUpdate();
    return;
  }
  els.updateButton.hidden = false;
}

// If a reload for this build still came back with the old page, something
// between here and the server is caching it; offer the button rather than
// reloading on every return to the app.
const UPDATE_RELOAD_KEY = "tmhi-control-center-reloaded-for";

function alreadyReloadedFor(build) {
  try {
    return Boolean(build) && window.sessionStorage.getItem(UPDATE_RELOAD_KEY) === build;
  } catch {
    return false;
  }
}

function reloadForUpdate() {
  try {
    if (state.updateBuild) {
      window.sessionStorage.setItem(UPDATE_RELOAD_KEY, state.updateBuild);
    }
  } catch {
    // Storage unavailable: the reload still goes ahead.
  }
  window.location.reload();
}

// A reload would lose whatever is in progress: typing, a running test or
// sweep, a drag, or a live aiming session.
function canReloadForUpdate() {
  const active = document.activeElement;
  const typing =
    active?.matches?.("input, textarea, select") &&
    !["checkbox", "radio", "button"].includes(active.type);
  return !(
    typing ||
    state.actionBusy ||
    state.speedTestBusy ||
    state.seriesRunning ||
    state.timelineDragging ||
    state.mapBusy ||
    state.gatewayLoginBusy ||
    state.snapshotBusy ||
    (state.activeView === "aim" && state.aimTimer)
  );
}

async function refreshTelemetryHistory(hours) {
  state.telemetryHours = Math.max(1, Math.min(336, Number(hours) || 6));
  renderTelemetryTrends();
  try {
    state.telemetryHistory = await api(
      `/api/gateway/telemetry/history?hours=${state.telemetryHours}`
    );
    renderTelemetryTrends();
  } catch (error) {
    showError(`Telemetry history: ${error.message}`);
  }
}

async function refreshConnectionHistory(days) {
  state.connectionDays = Math.max(1, Math.min(90, Number(days) || 14));
  renderConnectionStability();
  try {
    state.connectionHistory = await api(
      `/api/connection/history?days=${state.connectionDays}`
    );
    renderConnectionStability();
    renderTelemetryTrends();
    renderSpeedTests();
  } catch (error) {
    showError(`Connection history: ${error.message}`);
  }
}

async function refreshSpeedTestHistory(days, range = String(days)) {
  state.speedTestDays = Math.max(1, Math.min(730, Number(days) || 1));
  state.speedTestRange = range;
  renderSpeedTests();
  try {
    state.speedTestHistory = await api(
      `/api/speedtest/history?days=${state.speedTestDays}`
    );
    renderSpeedTests();
  } catch (error) {
    showError(`Speed history: ${error.message}`);
  }
}

async function downloadSnapshot() {
  if (state.snapshotBusy) {
    return;
  }

  state.snapshotBusy = true;
  updateControlState();
  setActionMessage("Building redacted homelab snapshot.", "");
  hideError();

  try {
    const snapshot = await api("/api/homelab/snapshot?include_nearby=false");
    const serialized = JSON.stringify(snapshot, null, 2);
    const blob = new Blob([serialized], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = `tmhi-control-center-snapshot-${new Date()
      .toISOString()
      .replace(/[:.]/g, "-")}.json`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    URL.revokeObjectURL(url);
    setActionMessage("Snapshot downloaded.", "success");
  } catch (error) {
    setActionMessage(error.message, "error");
  } finally {
    state.snapshotBusy = false;
    updateControlState();
  }
}

async function api(path, options = {}) {
  const init = {
    method: options.method || "GET",
    headers: {},
  };
  if (options.body !== undefined) {
    init.headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(options.body);
  }

  const response = await fetch(path, init);
  const text = await response.text();
  let payload = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = text;
    }
  }

  if (!response.ok) {
    throw new Error(readError(payload, response.status));
  }
  return payload;
}

function readError(payload, status) {
  if (payload && typeof payload === "object" && payload.detail) {
    return payload.detail;
  }
  if (typeof payload === "string" && payload.trim()) {
    return payload.trim();
  }
  return `HTTP ${status}`;
}

function renderAll() {
  renderHeader();
  renderOverviewMetrics();
  renderRadioStack();
  renderTelemetryTrends();
  renderSpeedTests();
  renderConnectionStability();
  renderSignal();
  renderDetails();
  renderControls();
  renderClients();
  renderHomelabInsights();
  renderTowerMapSummary();
  renderProbes();
  renderEvents();
  renderGatewaySections();
}

function renderHeader() {
  const detection = state.overview?.detection || {};
  const device = state.overview?.device || {};
  const connection = state.overview?.connection || {};
  const title = compactJoin([device.manufacturer, device.model]) || device.name;
  const network = compactJoin([connection.network_type, connection.band], " / ");

  setText(els.gatewayIdentity, title || "Gateway dashboard");
  setText(
    els.gatewaySubtitle,
    compactJoin([device.name, network, formatDate(state.overview?.observed_at)], " - ") ||
      "Waiting for gateway telemetry"
  );

  if (detection.reachable === true) {
    setTag(
      els.gatewayReachTag,
      detection.supported === false ? "Detected, limited" : "Gateway online",
      detection.supported === false ? "warn" : "good"
    );
  } else if (detection.reachable === false) {
    setTag(els.gatewayReachTag, "Gateway offline", "bad");
  } else {
    setTag(els.gatewayReachTag, "Detecting", "muted");
  }
}

function renderOverviewMetrics() {
  const status = state.status || {};
  const overview = state.overview || {};
  const detection = overview.detection || {};
  const signal = overview.signal || {};
  const connection = overview.connection || {};
  const system = overview.system || {};

  setText(els.internetMetric, booleanLabel(status.internet_online, "Online", "Offline"));
  setTone(els.internetMetric, toneFromBoolean(status.internet_online));
  setText(els.internetDetail, status.last_error || phaseText(status.phase) || "No check yet");

  const gatewayLabel =
    detection.model ||
    status.gateway_model ||
    detection.name ||
    status.gateway_name ||
    booleanLabel(detection.reachable ?? status.gateway_reachable, "Reachable", "Not found");
  setText(els.gatewayMetric, gatewayLabel);
  setTone(els.gatewayMetric, toneFromBoolean(detection.reachable ?? status.gateway_reachable));
  setText(els.gatewayDetail, detection.api_type || status.gateway_api_type || "Local API");

  const score = signal.score;
  setText(els.signalScore, Number.isFinite(score) ? `${score}%` : "--");
  setTone(els.signalScore, toneFromQuality(signal.quality));
  setText(els.signalQuality, signal.quality || "Unknown");

  const mode = connection.mode || connection.network_type || "Unknown";
  setText(els.radioModeMetric, mode);
  setTone(els.radioModeMetric, mode === "Unknown" ? "muted" : "info");
  setText(
    els.radioModeDetail,
    compactJoin([connection.operator, connection.band]) || "Cellular link"
  );

  const temperature = system.temperature;
  const hasTemperature = isFiniteReading(temperature?.celsius);
  els.temperatureMetricCard.hidden = !hasTemperature;
  if (hasTemperature) {
    setText(els.temperatureMetric, temperature.display || `${temperature.celsius} C`);
    setTone(els.temperatureMetric, "info");
    setText(els.temperatureDetail, `${formatValue(temperature.fahrenheit)} F`);
  }

  setText(els.uptimeMetric, system.uptime || connection.uptime || "--");
  setTone(els.uptimeMetric, system.uptime || connection.uptime ? "good" : "muted");
  setText(els.uptimeDetail, system.update_state ? `Update ${system.update_state}` : "Gateway runtime");

  const clientCount = state.clients?.count ?? state.clients?.devices?.length ?? 0;
  setText(els.connectedMetric, String(clientCount));
  setTone(els.connectedMetric, clientCount ? "info" : "muted");
  setText(els.connectedDetail, clientCount === 1 ? "Connected client" : "Connected clients");

  const probes = `${status.successful_probes || 0} / ${status.total_probes || 0}`;
  setText(els.probeMetric, probes);
  setTone(
    els.probeMetric,
    status.total_probes && status.successful_probes >= status.total_probes ? "good" : "warn"
  );
  setText(els.probeDetail, `${state.config?.minimum_successful_probes || 0} required`);

  setText(els.dryRunMetric, status.dry_run ? "Dry run" : "Live");
  setTone(els.dryRunMetric, status.dry_run ? "warn" : "good");
  setText(els.watchdogMetric, status.watchdog_enabled ? "Watchdog enabled" : "Watchdog off");

  setText(
    els.lastCheckMetric,
    status.last_check_at ? formatTime(new Date(status.last_check_at)) : "Never"
  );
  setText(els.lastOnlineMetric, status.last_online_at ? `Online ${formatDate(status.last_online_at)}` : "Online history");

  setText(els.rebootMetric, String(status.reboot_count_24h || 0));
  setTone(els.rebootMetric, status.reboot_count_24h ? "warn" : "muted");

  setTag(els.watchdogPhaseTag, phaseText(status.phase) || "Initializing", toneFromPhase(status.phase));
}

function renderHomelabInsights() {
  const insights = buildUiInsights();
  const readiness = insights.readiness;
  const readinessLabel = `${readiness.score}% ${readiness.label}`;
  const readinessTone = toneFromReadiness(readiness);

  setTag(els.dashboardReadinessTag, readinessLabel, readinessTone);
  setTag(els.homelabReadinessTag, readinessLabel, readinessTone);
  setText(els.dashboardNextAction, readiness.next_best_action);
  setText(els.homelabScore, `${readiness.score}%`);
  setText(els.homelabSummary, readiness.summary);

  renderChecklist(els.dashboardSetupList, insights.setup_steps.slice(0, 4), { compact: true });
  renderChecklist(els.homelabSetupList, insights.setup_steps, { compact: false });
  renderInsightList(els.homelabSignalCoach, insights.signal_coach);
  renderPlaybook(els.homelabPlaybook, insights.homelab_cards);
}

function buildUiInsights() {
  const setupSteps = buildSetupSteps();
  return {
    readiness: buildReadiness(setupSteps),
    setup_steps: setupSteps,
    signal_coach: buildSignalCoach(),
    homelab_cards: buildHomelabCards(),
  };
}

function buildReadiness(setupSteps) {
  const totalWeight = setupSteps.reduce((sum, step) => sum + step.weight, 0) || 1;
  const earned = setupSteps
    .filter((step) => step.status === "done" || step.status === "optional")
    .reduce((sum, step) => sum + step.weight, 0);
  const score = Math.round((earned / totalWeight) * 100);
  const next = setupSteps.find((step) => step.status !== "done" && step.status !== "optional");
  const signalScore = numericScore(state.overview?.signal?.score);
  const online = state.status?.internet_online;
  let label = "Needs setup";
  if (score >= 85 && (!Number.isFinite(signalScore) || signalScore >= 70)) {
    label = "Dialed in";
  } else if (score >= 65) {
    label = "Operational";
  } else if (online === false) {
    label = "Needs recovery";
  }

  let summary = "Start with gateway login, map center, and a baseline signal reading.";
  if (online === false) {
    summary = "Internet probes are failing. Check gateway reachability, then run a manual check before rebooting.";
  } else if (Number.isFinite(signalScore) && signalScore < 50) {
    summary = "Core setup is usable, but signal quality should be tuned before chasing firmware or tower changes.";
  } else if (score >= 85) {
    summary = "The key setup pieces are in place. Use sweeps and snapshots to tune placement over time.";
  } else if (score >= 65) {
    summary = "The control center is usable. Finish the remaining setup items to make troubleshooting easier.";
  }

  return {
    score,
    label,
    summary,
    next_best_action: next ? next.action : "Run a placement sweep and save the snapshot.",
  };
}

function buildSetupSteps() {
  const advanced = state.config?.advanced_modem || {};
  const mapConfig = state.config?.map || {};
  const detection = state.overview?.detection || {};
  const provider = state.mapData?.provider || {};
  const center = state.mapData?.map?.center || {};
  const clients = state.clients?.devices || [];
  const clientCount = state.clients?.count ?? clients.length;
  const backupCount = Array.isArray(state.firmwareBackups?.backups)
    ? state.firmwareBackups.backups.length
    : 0;
  const signalScore = numericScore(state.overview?.signal?.score);
  const g4arEnabled = isG4ARLabMode(advanced.mode);
  const skipStockBackup = Boolean(advanced.skip_stock_backup);

  const steps = [
    setupStep(
      "gateway-login",
      "Gateway login saved",
      Boolean(state.config?.gateway_password_configured),
      "Save the admin password once so Wi-Fi, clients, reboot, and backup tools work without retyping it.",
      "Open Settings, save the gateway admin password, then press Test.",
      18
    ),
    setupStep(
      "gateway-api",
      "Gateway API reachable",
      detection.reachable === true || state.status?.gateway_reachable === true,
      "The app needs the local gateway API, usually 192.168.12.1 on port 8080.",
      "Join the gateway LAN/Wi-Fi and verify the gateway host and port in Settings.",
      16
    ),
    setupStep(
      "signal-baseline",
      "Signal baseline captured",
      Number.isFinite(signalScore),
      "A baseline lets you compare antenna direction, placement, bands, and tower changes.",
      "Refresh the dashboard and record RSRP, RSRQ, SINR, band, PCI, and cell ID.",
      14,
      { warn: Number.isFinite(signalScore) && signalScore < 50 }
    ),
    setupStep(
      "map-center",
      "Map center saved",
      mapConfig.latitude !== null && mapConfig.latitude !== undefined && mapConfig.longitude !== null && mapConfig.longitude !== undefined,
      "A saved home location makes tower searches and serving-cell estimates much more useful.",
      "Open Map, use browser location or paste coordinates, then save the map center.",
      12,
      { warn: center.source === "public_ip" }
    ),
    setupStep(
      "tower-provider",
      "Tower lookup ready",
      Boolean(provider.configured || mapConfig.opencellid_configured),
      "OpenCellID is optional, but it unlocks nearby tower records and serving-cell map matches.",
      "Add an OpenCellID key in Settings, then refresh towers on the Map page.",
      10
    ),
    setupStep(
      "lan-inventory",
      "LAN inventory loaded",
      clientCount > 0,
      "Connected-device inventory helps catch unknown clients and identify which devices are stressing upload.",
      "Open Devices and run Reverse Lookup after saving the gateway login.",
      9,
      { warn: Boolean(state.config?.gateway_password_configured) && clientCount === 0 }
    ),
    setupStep(
      "watchdog-policy",
      "Watchdog policy reviewed",
      Boolean(state.status?.dry_run) || Boolean(state.config?.gateway_password_configured),
      "Dry Run keeps reboot automation safe until the gateway login and recovery behavior have been tested.",
      "Keep Dry Run on until manual checks and reboot recovery look predictable.",
      8
    ),
  ];

  if (g4arEnabled && backupCount === 0 && skipStockBackup) {
    steps.push({
      id: "g4ar-backup",
      title: "Recovery bundle reminder skipped",
      status: "skipped",
      tone: "warn",
      detail:
        "The reminder is suppressed, but firmware override still requires a separate raw partition backup and recovery path.",
      action: "Create the Docker recovery bundle before any radio-profile experiment.",
      weight: 13,
    });
  } else if (g4arEnabled) {
    steps.push(
      setupStep(
        "g4ar-backup",
        "G4AR Docker recovery bundle saved",
        backupCount > 0,
        "Docker saves stock API settings, firmware inventory, radio data, recovery notes, and checksums.",
        "Save the gateway login, enable owner lab, then create and download a recovery bundle.",
        13,
        { warn: Boolean(state.config?.gateway_password_configured) && backupCount === 0 }
      )
    );
  } else {
    steps.push({
      id: "g4ar-lab",
      title: "G4AR lab disabled",
      status: "optional",
      tone: "muted",
      detail: "Advanced firmware/radio work is optional and should stay disabled on stock or leased hardware.",
      action: "Enable only for owner-controlled G4AR units with a recovery path.",
      weight: 6,
    });
  }

  return steps;
}

function setupStep(id, title, done, detail, action, weight, { warn = false } = {}) {
  let status = "todo";
  let tone = "warn";
  if (done && warn) {
    status = "warn";
    tone = "warn";
  } else if (done) {
    status = "done";
    tone = "good";
  }
  return { id, title, status, tone, detail, action, weight };
}

function buildSignalCoach() {
  const signal = state.overview?.signal || {};
  const connection = state.overview?.connection || {};
  const metrics = Array.isArray(signal.metrics) ? signal.metrics : [];
  const byKey = Object.fromEntries(metrics.map((metric) => [String(metric.key || "").toLowerCase(), metric]));
  const tips = [];
  const sinr = numericScore(byKey.sinr?.score);
  const rsrp = numericScore(byKey.rsrp?.score);
  const rsrq = numericScore(byKey.rsrq?.score);
  const band = String(connection.band || "").toLowerCase();

  if (!Number.isFinite(sinr) && !Number.isFinite(rsrp) && !Number.isFinite(rsrq)) {
    tips.push(tip("Capture radio metrics", "Refresh after the gateway API responds. RSRP, RSRQ, SINR, band, PCI, and cell ID make every antenna move measurable.", "warn"));
  }
  if (Number.isFinite(sinr) && sinr < 70) {
    tips.push(tip("Prioritize SINR before bars", "Rotate the gateway or directional antenna in small steps and keep the position that improves SINR without crushing RSRP.", sinr >= 45 ? "warn" : "bad"));
  }
  if (Number.isFinite(rsrp) && rsrp < 60) {
    tips.push(tip("Improve received power", "Move the gateway higher, closer to an exterior wall/window, or aim the antenna at the best mapped cell.", rsrp >= 35 ? "warn" : "bad"));
  }
  if (Number.isFinite(rsrq) && rsrq < 55) {
    tips.push(tip("Watch congestion and reflections", "Weak RSRQ often means noisy or loaded air. Compare another band/tower before assuming the closest site is best.", "warn"));
  }
  if (band.includes("n41")) {
    tips.push(tip("n41 detected", "n41 can be excellent for download. If upload or latency is weak, compare placement and LTE-anchor behavior on owned lab hardware.", "info"));
  }
  if (state.mapData?.connected?.location) {
    tips.push(tip("Serving tower is mapped", "Use the map line as an aiming baseline, then run a sweep after each antenna or placement change.", "good"));
  }
  tips.push(tip("Run repeatable sweeps", "Change one thing at a time, wait for the gateway to settle, then compare signal, ping, loss, and connected cell.", "info"));
  return tips.slice(0, 6);
}

function buildHomelabCards() {
  const clients = state.clients?.devices || [];
  const clientCount = state.clients?.count ?? clients.length;
  const signalScore = numericScore(state.overview?.signal?.score);
  const radioEnabled = state.wifi?.radio_enabled;
  const provider = state.mapData?.provider || {};
  return [
    {
      title: "Router offload mode",
      tone: radioEnabled === false ? "good" : "info",
      summary:
        radioEnabled === false
          ? "Gateway Wi-Fi radios are off. Your own router can own Wi-Fi, DNS, VLANs, and SQM."
          : "Use Devices to turn gateway Wi-Fi off when an external router handles the LAN.",
      actions: [
        "Put your router WAN behind the gateway LAN.",
        "Run DHCP, DNS, VLANs, and Wi-Fi from the router.",
        "Document double-NAT or port-forwarding limits for services.",
      ],
    },
    {
      title: "Upload and latency tuning",
      tone: Number.isFinite(signalScore) && signalScore < 50 ? "warn" : "info",
      summary: "Use SQM/QoS on your own router to protect video calls, gaming, VPN, and remote access from upload bufferbloat.",
      actions: [
        "Measure real upload at different times of day.",
        "Set SQM uplink slightly below stable upload speed.",
        "Retest ping under load after each change.",
      ],
    },
    {
      title: "Tower and antenna notebook",
      tone: provider.nearby_loaded ? "good" : "info",
      summary: "Track band, PCI, cell ID, SINR, RSRP, speed, and antenna direction so changes are repeatable.",
      actions: [
        "Save the map center.",
        "Refresh nearby towers.",
        "Run sweeps after each antenna angle or gateway placement change.",
      ],
    },
    {
      title: "LAN inventory",
      tone: clientCount ? "good" : "warn",
      summary: `${clientCount} connected device${clientCount === 1 ? "" : "s"} loaded.`,
      actions: [
        "Run reverse lookup after adding the gateway login.",
        "Rename important devices in your router/DNS notes.",
        "Watch for unknown clients before blaming the cellular link.",
      ],
    },
    {
      title: "Recovery discipline",
      tone: state.status?.dry_run ? "warn" : "good",
      summary: "Keep changes reversible: backup configs, export snapshots, and avoid live reboot automation until recovery is proven.",
      actions: [
        "Download a snapshot before lab changes.",
        "Keep Dry Run on during first setup.",
        "Power the gateway and router from a UPS if possible.",
      ],
    },
    {
      title: "Event context",
      tone: "info",
      summary: `${state.events.length} recent event${state.events.length === 1 ? "" : "s"} in the local log.`,
      actions: [
        "Compare outages with weather, load, tower changes, and router logs.",
        "Keep snapshots with antenna placement notes.",
      ],
    },
  ];
}

function renderChecklist(container, steps, { compact }) {
  replaceChildren(container);
  if (!steps.length) {
    container.append(emptyNode("No setup items are available yet."));
    return;
  }
  for (const step of steps) {
    const item = document.createElement("article");
    item.className = `check-item check-item--${step.tone || "muted"}`;

    const status = document.createElement("span");
    status.className = "check-status";
    status.textContent = step.status === "todo" ? "Next" : humanize(step.status);

    const body = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = step.title;
    const detail = document.createElement("p");
    detail.textContent = step.detail;
    body.append(title, detail);
    if (!compact || step.status !== "done") {
      const action = document.createElement("small");
      action.textContent = step.action;
      body.append(action);
    }

    item.append(status, body);
    container.append(item);
  }
}

function renderInsightList(container, insights) {
  replaceChildren(container);
  if (!insights.length) {
    container.append(emptyNode("No recommendations yet."));
    return;
  }
  for (const insight of insights) {
    const item = document.createElement("article");
    item.className = `insight-card insight-card--${insight.tone || "info"}`;
    const title = document.createElement("strong");
    title.textContent = insight.title;
    const detail = document.createElement("p");
    detail.textContent = insight.detail;
    item.append(title, detail);
    container.append(item);
  }
}

function renderPlaybook(container, cards) {
  replaceChildren(container);
  if (!cards.length) {
    container.append(emptyNode("No playbook items yet."));
    return;
  }
  for (const card of cards) {
    const item = document.createElement("article");
    item.className = `playbook-card playbook-card--${card.tone || "info"}`;
    const title = document.createElement("strong");
    title.textContent = card.title;
    const summary = document.createElement("p");
    summary.textContent = card.summary;
    const list = document.createElement("ul");
    for (const action of card.actions || []) {
      const row = document.createElement("li");
      row.textContent = action;
      list.append(row);
    }
    item.append(title, summary, list);
    container.append(item);
  }
}

function renderOrderedList(container, values) {
  replaceChildren(container);
  for (const value of values || []) {
    const item = document.createElement("li");
    item.textContent = value;
    container.append(item);
  }
}

function tip(title, detail, tone) {
  return { title, detail, tone };
}

function toneFromReadiness(readiness) {
  if (readiness.label === "Dialed in") {
    return "good";
  }
  if (readiness.label === "Operational") {
    return "info";
  }
  if (readiness.label === "Needs recovery") {
    return "bad";
  }
  return "warn";
}

function renderRadioStack() {
  const radios = Array.isArray(state.overview?.radios) ? state.overview.radios : [];
  const advanced = Boolean(state.overview?.telemetry?.advanced_cell_available);
  setTag(
    els.advancedCellTag,
    advanced ? "Advanced cell data" : "Basic telemetry",
    advanced ? "good" : "muted"
  );
  setText(
    els.telemetryFreshness,
    state.overview?.observed_at ? `Sampled ${formatDate(state.overview.observed_at)}` : "Waiting for data"
  );

  replaceChildren(els.radioCards);
  if (!radios.length) {
    els.radioCards.append(emptyNode("No LTE or 5G radio blocks were returned by this firmware."));
    return;
  }

  for (const radio of radios) {
    const card = document.createElement("article");
    card.className = `radio-status-card radio-status-card--${radio.key || "unknown"}`;

    const header = document.createElement("div");
    header.className = "radio-card-header";
    const titleGroup = document.createElement("div");
    const eyebrow = document.createElement("span");
    eyebrow.textContent = radio.active === false ? "Not registered" : "Active radio";
    const title = document.createElement("h3");
    title.textContent = radio.label || humanize(radio.key);
    titleGroup.append(eyebrow, title);
    const quality = document.createElement("span");
    quality.className = `tag tag--${toneFromQuality(radio.quality)}`;
    quality.textContent = Number.isFinite(radio.score)
      ? `${radio.score}% ${radio.quality || ""}`.trim()
      : radio.active === false
        ? "Idle"
        : "Connected";
    header.append(titleGroup, quality);

    const metricGrid = document.createElement("div");
    metricGrid.className = "radio-metric-grid";
    const metrics = Array.isArray(radio.metrics) ? radio.metrics : [];
    for (const metric of metrics) {
      const metricNode = document.createElement("div");
      metricNode.className = `radio-metric radio-metric--${toneFromQuality(metric.rating)}`;
      const label = document.createElement("span");
      label.textContent = metric.label || humanize(metric.key);
      const value = document.createElement("strong");
      value.textContent = metric.display || formatValue(metric.value);
      metricNode.append(label, value);
      metricGrid.append(metricNode);
    }

    const facts = document.createElement("dl");
    facts.className = "radio-fact-grid";
    const cell = radio.cell && typeof radio.cell === "object" ? radio.cell : {};
    const factEntries = [
      ["Band", cell.band],
      ["Bandwidth", cell.bandwidth],
      ["Antenna", radio.antenna],
      ["PCI", cell.pci],
      [cell.arfcn_label || "Channel", cell.arfcn],
      ["Cell ID", cell.cell_id],
      [cell.node_label || "Node ID", cell.node_id],
      ["TAC", cell.tac],
    ].filter(([, value]) => hasDisplayValue(value));
    for (const [labelText, valueText] of factEntries) {
      const item = document.createElement("div");
      const term = document.createElement("dt");
      term.textContent = labelText;
      const value = document.createElement("dd");
      value.textContent = formatValue(valueText);
      item.append(term, value);
      facts.append(item);
    }

    if (!metrics.length) {
      metricGrid.append(emptyNode("Signal measurements are not exposed for this radio."));
    }
    card.append(header, metricGrid);
    if (factEntries.length) {
      card.append(facts);
    }
    if (radio.note) {
      const note = document.createElement("p");
      note.className = "radio-card-note";
      note.textContent = radio.note;
      card.append(note);
    }
    els.radioCards.append(card);
  }
}

function renderTelemetryTrends() {
  const points = telemetryPointsWithCurrent();
  const hasTemperature = isFiniteReading(
    state.overview?.system?.temperature?.celsius
  );
  const storedCount = Number(state.telemetryHistory?.count || 0);
  const collector = state.telemetryHistory?.collector || {};
  const configuredCollector = state.config?.telemetry_history || {};
  const collectorEnabled = collector.enabled ?? configuredCollector.enabled ?? true;
  const collectorInterval = Number(
    collector.interval_seconds || configuredCollector.sample_interval_seconds || 60
  );
  const intervalLabel = collectorInterval >= 60
    ? `${Math.round(collectorInterval / 60)}m`
    : `${Math.round(collectorInterval)}s`;
  const collectorError = collector.last_error;
  setTag(
    els.telemetryHistoryTag,
    storedCount
      ? `${storedCount} / ${formatHistoryRange(state.telemetryHours)} / auto ${intervalLabel}`
      : collectorEnabled
        ? `Auto collecting / ${intervalLabel}`
        : "Collection off",
    collectorError ? "warn" : storedCount >= 2 || collectorEnabled ? "good" : "muted"
  );
  document.querySelectorAll("[data-telemetry-hours]").forEach((button) => {
    button.classList.toggle("is-active", Number(button.dataset.telemetryHours) === state.telemetryHours);
  });

  const markers = connectionMarkers();
  renderLineChart(
    els.rsrpTrendChart,
    points,
    [
      { key: "lte", label: "4G LTE", className: "chart-series--lte", read: (point) => point.radios?.lte?.metrics?.rsrp },
      { key: "nr", label: "5G NR", className: "chart-series--nr", read: (point) => point.radios?.nr?.metrics?.rsrp },
    ],
    { unit: "dBm", decimals: 0, markers, emptyText: "RSRP history will appear after two gateway samples." }
  );
  renderLineChart(
    els.sinrTrendChart,
    points,
    [
      { key: "lte", label: "4G LTE", className: "chart-series--lte", read: (point) => point.radios?.lte?.metrics?.sinr },
      { key: "nr", label: "5G NR", className: "chart-series--nr", read: (point) => point.radios?.nr?.metrics?.sinr },
    ],
    { unit: "dB", decimals: 0, markers, emptyText: "SINR history will appear when the gateway exposes it." }
  );
  renderLineChart(
    els.cqiTrendChart,
    points,
    [
      { key: "lte", label: "4G LTE", className: "chart-series--lte", read: (point) => point.radios?.lte?.metrics?.cqi },
      { key: "nr", label: "5G NR", className: "chart-series--nr", read: (point) => point.radios?.nr?.metrics?.cqi },
    ],
    { unit: "", decimals: 0, markers, emptyText: "CQI history needs the gateway login for advanced cell data." }
  );
  els.temperatureMetricCard.hidden = !hasTemperature;
  els.temperatureTrendPanel.hidden = !hasTemperature;
  // Three charts sit in one row; a fourth (temperature) makes a 2x2 grid.
  els.telemetryTrendGrid.classList.toggle("trend-grid--two", hasTemperature);
  if (hasTemperature) {
    renderLineChart(
      els.temperatureTrendChart,
      points,
      [
        { key: "temperature", label: "Gateway", className: "chart-series--thermal", read: (point) => point.system?.temperature_c },
      ],
      { unit: "C", decimals: 1, markers, emptyText: "Temperature history will appear after two sensor samples." }
    );
  } else {
    replaceChildren(els.temperatureTrendChart);
  }
}

function speedTestUsageEstimate(cadence, profile) {
  const perRunBytes = SPEED_TEST_PROFILE_BYTES[profile] || SPEED_TEST_PROFILE_BYTES.gentle;
  const runsPerDay = SPEED_TEST_RUNS_PER_DAY[cadence] ?? 0;
  return {
    perRunBytes,
    runsPerDay,
    dailyBytes: perRunBytes * runsPerDay,
    thirtyDayBytes: perRunBytes * runsPerDay * 30,
  };
}

function speedTestRetentionDays() {
  return Number(
    state.speedTestStatus?.retention_days ||
      state.config?.speed_test?.retention_days ||
      730
  );
}

function speedTestDefaultRange(cadence) {
  return SPEED_TEST_DEFAULT_RANGE[cadence] || "1";
}

function speedTestRangeToDays(range) {
  return range === "all" ? speedTestRetentionDays() : Number(range);
}

// Widen the history window to match the configured cadence, unless the reader
// has already chosen a range themselves this session.
async function applySpeedTestDefaultRange() {
  if (state.speedTestRangePinned) {
    return;
  }
  const cadence =
    state.speedTestStatus?.cadence || state.config?.speed_test?.cadence;
  if (!cadence) {
    return;
  }
  let range = speedTestDefaultRange(cadence);
  let days = speedTestRangeToDays(range);
  if (!Number.isFinite(days)) {
    return;
  }
  const retentionDays = speedTestRetentionDays();
  if (days > retentionDays) {
    range = "all";
    days = retentionDays;
  }
  if (range === state.speedTestRange) {
    return;
  }
  await refreshSpeedTestHistory(days, range);
}

function formatRetention(days) {
  const value = Number(days) || 730;
  const labels = {
    30: "30 days",
    90: "90 days",
    180: "6 months",
    365: "1 year",
    730: "2 years",
  };
  return labels[value] || `${value} days`;
}

function renderSpeedTestSchedulePreview() {
  const cadence = els.speedTestCadence.value || "disabled";
  const profile = els.speedTestProfile.value || "gentle";
  const usage = speedTestUsageEstimate(cadence, profile);
  const intervalLabels = {
    every_5_minutes: "5 minutes",
    every_10_minutes: "10 minutes",
    every_15_minutes: "15 minutes",
    every_30_minutes: "30 minutes",
    hourly: "hour",
    every_6_hours: "6 hours",
    every_12_hours: "12 hours",
  };

  if (cadence === "disabled") {
    setText(
      els.speedTestScheduleDetail,
      `${formatDataSize(usage.perRunBytes)} per manual run. Automatic tests do not use data.`
    );
    setText(els.speedTestUsageEstimate, "No scheduled test traffic");
    setText(els.speedTestUsageWarning, "Manual tests use the currently saved profile.");
    els.speedTestUsageWarning.classList.remove("is-warning", "is-danger");
    return;
  }

  const scheduleDetail = intervalLabels[cadence]
    ? `Runs every ${intervalLabels[cadence]} from the time this schedule is saved.`
    : "Run times rotate through night, morning, afternoon, and evening.";
  setText(
    els.speedTestScheduleDetail,
    `${formatDataSize(usage.perRunBytes)} maximum per run. ${scheduleDetail}`
  );
  setText(
    els.speedTestUsageEstimate,
    `${formatDataSize(usage.dailyBytes)} per day; ${formatDataSize(usage.thirtyDayBytes)} per 30 days`
  );

  const warnings = [];
  if (usage.runsPerDay >= 144) {
    warnings.push(
      `${usage.runsPerDay.toFixed(0)} tests per day can briefly compete with active internet use.`
    );
  }
  if (usage.thirtyDayBytes >= 500_000_000_000) {
    warnings.push("This selection can exceed 500 GB of test traffic in 30 days.");
  } else if (usage.thirtyDayBytes >= 100_000_000_000) {
    warnings.push("This selection can exceed 100 GB of test traffic in 30 days.");
  }
  setText(
    els.speedTestUsageWarning,
    warnings.join(" ") || "Estimated maximum; failed or interrupted tests may use less."
  );
  els.speedTestUsageWarning.classList.toggle(
    "is-danger",
    usage.thirtyDayBytes >= 500_000_000_000
  );
  els.speedTestUsageWarning.classList.toggle(
    "is-warning",
    usage.thirtyDayBytes >= 100_000_000_000 && usage.thirtyDayBytes < 500_000_000_000
  );
}

function renderSpeedTests() {
  const status = state.speedTestStatus || {};
  const history = state.speedTestHistory || {};
  const points = Array.isArray(history.points) ? history.points : [];
  const successful = points.filter((point) => point.success);
  const latest = successful.length ? successful[successful.length - 1] : null;
  const cadence = status.cadence || state.config?.speed_test?.cadence || "disabled";
  const profileKey = status.profile?.key || state.config?.speed_test?.profile || "gentle";
  const cadenceLabels = {
    disabled: "Automatic tests off",
    every_5_minutes: "Every 5 minutes",
    every_10_minutes: "Every 10 minutes",
    every_15_minutes: "Every 15 minutes",
    every_30_minutes: "Every 30 minutes",
    hourly: "Hourly schedule",
    every_6_hours: "Every 6 hours",
    every_12_hours: "Every 12 hours",
    daily: "Daily schedule",
    weekly: "Weekly schedule",
    monthly: "Monthly schedule",
  };

  setTag(
    els.speedTestHistoryTag,
    status.running || state.speedTestBusy
      ? "Test running"
      : cadenceLabels[cadence] || "Schedule unknown",
    status.running || state.speedTestBusy ? "warn" : cadence === "disabled" ? "muted" : "good"
  );
  // Surface the configured test size next to the heading: it decides how much
  // data each run spends, and it was otherwise only visible in Settings.
  const profile = status.profile || {};
  const profileLabel = profile.label || humanize(profileKey);
  const perRunBytes = Number.isFinite(profile.estimated_bytes)
    ? profile.estimated_bytes
    : SPEED_TEST_PROFILE_BYTES[profileKey] || 0;
  setText(
    els.speedTestProfileLabel,
    perRunBytes
      ? `${profileLabel} profile \u00b7 ${formatDataSize(perRunBytes)} per test`
      : `${profileLabel} profile`,
  );

  setText(els.speedTestDownload, formatSpeedResult(latest?.download_mbps));
  setText(els.speedTestUpload, formatSpeedResult(latest?.upload_mbps));
  setText(els.speedTestLatency, formatMillisecondResult(latest?.latency_ms));
  setText(els.speedTestDataUsed, formatDataSize(history.total_bytes || 0));
  setText(
    els.speedTestDownloadDetail,
    latest ? `Measured ${formatDate(latest.observed_at)}` : "No samples yet"
  );
  setText(
    els.speedTestUploadDetail,
    history.averages?.upload_mbps != null
      ? `${formatSpeedResult(history.averages.upload_mbps)} average`
      : "No samples yet"
  );
  setText(
    els.speedTestLatencyDetail,
    latest?.jitter_ms != null ? `${formatMillisecondResult(latest.jitter_ms)} jitter` : "Idle sample"
  );
  setText(
    els.speedTestDataDetail,
    `${history.successful_count || 0} completed, ${history.failed_count || 0} failed; keep ${formatRetention(speedTestRetentionDays())}`
  );
  document.querySelectorAll("[data-speedtest-days]").forEach((button) => {
    button.classList.toggle(
      "is-active",
      button.dataset.speedtestDays === state.speedTestRange
    );
  });

  if (document.activeElement !== els.speedTestCadence) {
    els.speedTestCadence.value = cadence;
  }
  if (document.activeElement !== els.speedTestProfile) {
    els.speedTestProfile.value = profileKey;
  }
  if (document.activeElement !== els.speedTestRetention) {
    els.speedTestRetention.value = String(speedTestRetentionDays());
  }

  const nextRun = status.next_run_at ? formatDate(status.next_run_at) : "";
  // Dayparts follow the gateway's clock when it reports a zone, which keeps
  // them right across daylight-saving changes; otherwise the saved offset.
  const zoneNote = Number.isFinite(status.timezone_offset_minutes)
    ? ` · dayparts in ${formatUtcOffset(status.timezone_offset_minutes)}${
        status.timezone_source === "gateway" ? " from the gateway clock" : ""
      }`
    : "";
  setText(
    els.speedTestNextRun,
    nextRun
      ? `Next: ${nextRun}${status.next_daypart ? ` (${status.next_daypart})` : ""}${zoneNote}`
      : "Automatic tests are off"
  );
  renderSpeedTestSchedulePreview();

  renderLineChart(
    els.speedTestTrendChart,
    successful,
    [
      {
        key: "download",
        label: "Download",
        className: "chart-series--download",
        read: (point) => point.download_mbps,
      },
      {
        key: "upload",
        label: "Upload",
        className: "chart-series--upload",
        read: (point) => point.upload_mbps,
      },
    ],
    {
      unit: "Mbps",
      decimals: 1,
      historyHours: Number(history.range_days || state.speedTestDays) * 24,
      markers: connectionMarkers(),
      emptyText: "Run a test or enable a schedule to begin speed history.",
    }
  );

  // Averages per radio connection: the comparison that tells whether a mode
  // or band change actually moved throughput.
  replaceChildren(els.speedTestConnections);
  const connections = Array.isArray(history.connections) ? history.connections : [];
  els.speedTestConnections.hidden = !connections.length;
  for (const group of connections) {
    const item = document.createElement("article");
    item.className = "daypart-item";
    const label = document.createElement("span");
    label.textContent = group.label;
    const value = document.createElement("strong");
    value.textContent = `${Number(group.download_mbps).toFixed(0)} down / ${Number(group.upload_mbps).toFixed(0)} up`;
    const count = document.createElement("small");
    count.textContent = `${group.count} sample${group.count === 1 ? "" : "s"}${
      group.count < 5 ? " · too few to compare yet" : ""
    }`;
    item.append(label, value, count);
    els.speedTestConnections.append(item);
  }

  replaceChildren(els.speedTestDayparts);
  const dayparts = Array.isArray(history.dayparts) ? history.dayparts : [];
  for (const part of dayparts) {
    const item = document.createElement("article");
    item.className = "daypart-item";
    const label = document.createElement("span");
    label.textContent = part.label;
    const value = document.createElement("strong");
    value.textContent = part.count
      ? `${Number(part.download_mbps).toFixed(0)} down / ${Number(part.upload_mbps).toFixed(0)} up`
      : "No sample";
    const count = document.createElement("small");
    count.textContent = part.count ? `${part.count} sample${part.count === 1 ? "" : "s"}` : "Waiting";
    item.append(label, value, count);
    els.speedTestDayparts.append(item);
  }
  if (!dayparts.length) {
    els.speedTestDayparts.append(emptyNode("Daypart averages will appear as scheduled tests rotate."));
  }
}

// Handovers and restarts drawn onto the history charts, so a step in signal
// or throughput can be read against what the radio was doing at the time.
function connectionMarkers() {
  const changes = Array.isArray(state.connectionHistory?.changes)
    ? state.connectionHistory.changes
    : [];
  return changes
    .filter((event) => event.kind !== "registration_changed")
    .map((event) => ({
      time: new Date(event.timestamp).getTime(),
      label: event.message,
      tone: event.kind === "gateway_restarted" ? "restart" : "connection",
    }))
    .filter((marker) => Number.isFinite(marker.time));
}

function renderConnectionStability() {
  const history = state.connectionHistory;
  document.querySelectorAll("[data-stability-days]").forEach((button) => {
    button.classList.toggle(
      "is-active",
      Number(button.dataset.stabilityDays) === state.connectionDays
    );
  });
  if (!history) {
    setTag(els.stabilityTag, "Loading", "muted");
    return;
  }

  const outages = history.outages || {};
  const current = history.current;
  setText(
    els.stabilityCurrentLabel,
    current && current.mode !== "none"
      ? compactJoin(
          [
            `Now on ${current.label}`,
            current.bands,
            current.site ? `site ${current.site}` : "",
          ],
          " · "
        )
      : "Current connection unknown"
  );

  const rangeLabel = `${history.range_days} days`;
  const unrequested = Number(history.unrequested_restart_count || 0);
  const outageCount = Number(outages.count || 0);
  setTag(
    els.stabilityTag,
    outageCount || unrequested
      ? `${outageCount} outage${outageCount === 1 ? "" : "s"}, ${unrequested} restart${unrequested === 1 ? "" : "s"}`
      : "Stable",
    outageCount || unrequested ? "warn" : "good"
  );

  setText(els.outageCount, String(outageCount));
  setText(
    els.outageCountDetail,
    `${formatOutageDuration(outages.total_seconds || 0)} offline in ${rangeLabel}`
  );
  setText(
    els.outageMedian,
    outages.median_seconds != null ? formatOutageDuration(outages.median_seconds) : "--"
  );
  setText(
    els.outageMedianDetail,
    outages.longest_seconds != null
      ? `Longest ${formatOutageDuration(outages.longest_seconds)}; measured to ${outages.resolution_seconds} s`
      : "No outages in range"
  );
  setText(els.restartCount, String(history.restart_count || 0));
  setText(
    els.restartDetail,
    unrequested
      ? `${unrequested} not requested by this app`
      : history.restart_count
        ? "All requested by this app"
        : "None in range"
  );
  const changes = Array.isArray(history.changes) ? history.changes : [];
  const lastChange = changes.find((event) => event.kind === "connection_changed");
  setText(els.connectionChangeCount, String(history.change_count || 0));
  setText(
    els.connectionChangeDetail,
    lastChange ? `Last ${formatDate(lastChange.timestamp)}` : "No handovers in range"
  );

  renderOutageHours(outages);
  renderOutageBreakdown(outages);
  renderConnectionTimeline();
}

function renderOutageHours(outages) {
  const offset = Number(outages.timezone_offset_minutes);
  setText(
    els.outageHourZone,
    Number.isFinite(offset) ? `Gateway time, ${formatUtcOffset(offset)}` : "Gateway time"
  );
  replaceChildren(els.outageHourChart);
  const hourly = Array.isArray(outages.hourly) ? outages.hourly : [];
  if (!outages.count || hourly.length !== 24) {
    els.outageHourChart.append(emptyNode("No outages in this range."));
    return;
  }

  const peak = Math.max(...hourly, 1);
  const bars = document.createElement("div");
  bars.className = "hour-bars";
  bars.setAttribute("role", "img");
  bars.setAttribute(
    "aria-label",
    `Outage starts by hour; most at ${formatHour(outages.peak_hour)} with ${outages.peak_hour_count}`
  );
  hourly.forEach((count, hour) => {
    const bar = document.createElement("div");
    bar.className = "hour-bar";
    bar.classList.toggle("is-peak", count > 0 && count === peak);
    bar.style.setProperty("--level", String(count / peak));
    bar.title = `${formatHour(hour)}-${formatHour((hour + 1) % 24)}: ${count} outage${count === 1 ? "" : "s"}`;
    bars.append(bar);
  });
  const axis = document.createElement("div");
  axis.className = "hour-axis";
  for (const hour of [0, 6, 12, 18]) {
    const label = document.createElement("span");
    label.textContent = formatHour(hour);
    axis.append(label);
  }
  els.outageHourChart.append(bars, axis);
}

const TIMELINE_TYPES = {
  outage: { label: "Outages", title: "Internet outage", icon: "outage", tone: "red" },
  restart: { label: "Restarts", title: "Gateway restart", icon: "restart", tone: "magenta" },
  mode: { label: "Mode changes", title: "Mode change", icon: "mode", tone: "blue" },
  site: { label: "Site changes", title: "New cell site", icon: "site", tone: "blue" },
  sector: { label: "Sector changes", title: "Sector change", icon: "sector", tone: "teal" },
  band: { label: "Band changes", title: "Band change", icon: "band", tone: "teal" },
  cell: { label: "Cell changes", title: "Cell change", icon: "sector", tone: "teal" },
  firmware: { label: "Firmware", title: "Firmware update", icon: "firmware", tone: "amber" },
  registration: { label: "Registration", title: "Registration change", icon: "registration", tone: "amber" },
};

const MODE_SHORT_LABELS = {
  "5g_sa": "5G SA",
  nsa: "LTE+5G",
  lte: "LTE",
  none: "No service",
  unknown: "Not recorded",
};

const DIAGNOSIS_SHORT_LABELS = {
  upstream: "Radio up, fault upstream",
  cellular: "Cellular lost",
  gateway_unreachable: "Gateway silent",
};

// 24px stroke icons, drawn with currentColor so they follow the theme.
const ICON_PATHS = {
  restart: "M12 3v8 M6.3 6.3a8 8 0 1 0 11.4 0",
  mode: "M4 8h14 M14 4l4 4-4 4 M20 16H6 M10 12l-4 4 4 4",
  site: "M12 11v10 M8 21h8 M12 11l-4 10 M12 11l4 10 M8.5 7.5a5 5 0 0 1 7 0 M6 5a8.5 8.5 0 0 1 12 0",
  sector: "M21 12a9 9 0 1 1-3-6.7 M21 4v5h-5",
  band: "M3 12c2-4 4-4 6 0s4 4 6 0 4-4 6 0",
  firmware: "M7 7h10v10H7z M9 3v3 M15 3v3 M9 18v3 M15 18v3 M3 9h3 M3 15h3 M18 9h3 M18 15h3",
  registration: "M4 20v-3 M9 20v-7 M14 20V9 M19 20V5 M3 3l18 18",
  outage: "M9 17H7a5 5 0 0 1 0-10h2 M15 7h2a5 5 0 0 1 4 8 M8 12h3 M3 3l18 18",
  prev: "M15 18l-6-6 6-6",
  next: "M9 18l6-6-6-6",
};

const TIMELINE_ICON_SIZE = 22;
const TIMELINE_ICON_GAP = 3;
const TIMELINE_MAX_ROWS = 3;

function iconNode(name) {
  const svg = svgElement("svg", {
    viewBox: "0 0 24 24",
    class: "icon",
    "aria-hidden": "true",
    focusable: "false",
  });
  svg.append(svgElement("path", { d: ICON_PATHS[name] || "" }));
  return svg;
}

// Every selectable moment in range: logged changes plus outage periods.
function timelineEvents() {
  const history = state.connectionHistory || {};
  const items = [];
  for (const change of Array.isArray(history.changes) ? history.changes : []) {
    const type =
      change.kind === "connection_changed"
        ? change.details?.change || "cell"
        : {
            gateway_restarted: "restart",
            firmware_changed: "firmware",
            registration_changed: "registration",
          }[change.kind];
    const time = Date.parse(change.timestamp);
    if (!TIMELINE_TYPES[type] || !Number.isFinite(time)) {
      continue;
    }
    items.push({ key: `${change.kind}:${change.timestamp}`, type, time, event: change });
  }
  const periods = Array.isArray(history.outages?.periods) ? history.outages.periods : [];
  for (const outage of periods) {
    const time = Date.parse(outage.started_at);
    if (!Number.isFinite(time)) {
      continue;
    }
    const end = Date.parse(outage.ended_at || history.range_end);
    items.push({
      key: `outage:${outage.started_at}`,
      type: "outage",
      time,
      end: Number.isFinite(end) ? end : time,
      outage,
    });
  }
  return items.sort((left, right) => left.time - right.time);
}

// Mode bands between logged switches. Before the change log began the mode
// is unknown, not whatever the first switch happened to leave.
function timelineModeSegments(start, end) {
  const history = state.connectionHistory || {};
  const knownSince = Date.parse(history.known_since);
  const switches = (Array.isArray(history.changes) ? history.changes : [])
    .filter((event) => event.kind === "connection_changed" && event.details?.to)
    .map((event) => ({ time: Date.parse(event.timestamp), from: event.details.from, to: event.details.to }))
    .filter((item) => Number.isFinite(item.time))
    .sort((left, right) => left.time - right.time);

  const segments = [];
  let cursor = start;
  if (Number.isFinite(knownSince) && knownSince > start) {
    cursor = Math.min(knownSince, end);
    segments.push({ start, end: cursor, mode: { mode: "unknown" } });
  }
  let mode = switches.length ? switches[0].from : history.current;
  for (const item of switches) {
    if (item.time > cursor) {
      segments.push({ start: cursor, end: Math.min(item.time, end), mode });
      cursor = Math.min(item.time, end);
    }
    mode = item.to;
  }
  if (cursor < end) {
    segments.push({ start: cursor, end, mode: mode || history.current });
  }
  // A sector or site change keeps the mode; draw it as one continuous band.
  const merged = [];
  for (const segment of segments) {
    const previous = merged[merged.length - 1];
    if (
      previous &&
      previous.mode?.mode === segment.mode?.mode &&
      previous.mode?.bands === segment.mode?.bands
    ) {
      previous.end = segment.end;
    } else {
      merged.push({ ...segment });
    }
  }
  return merged.filter((segment) => segment.mode && segment.end > segment.start);
}

function renderConnectionTimeline() {
  if (state.timelineDragging) {
    return;
  }
  const container = els.connectionTimeline;
  const history = state.connectionHistory;
  replaceChildren(container);
  replaceChildren(els.timelineFilters);
  const start = Date.parse(history?.range_start);
  const end = Date.parse(history?.range_end);
  if (!Number.isFinite(start) || !Number.isFinite(end) || end <= start) {
    container.append(emptyNode("The timeline appears once connection history loads."));
    replaceChildren(els.timelineDetail);
    state.timelineVisible = [];
    return;
  }
  state.timelineRange = { start, span: end - start };
  const position = (time) => `${clamp(((time - start) / (end - start)) * 100, 0, 100)}%`;

  const items = timelineEvents();
  renderTimelineFilters(items);
  const visible = items.filter((item) => !state.timelineHidden.has(item.type));
  state.timelineVisible = visible;

  const labels = document.createElement("div");
  labels.className = "timeline-labels";
  for (const text of ["Mode", "Events", "Online"]) {
    const label = document.createElement("span");
    label.textContent = text;
    labels.append(label);
  }

  const plot = document.createElement("div");
  plot.className = "timeline-plot";

  const grid = document.createElement("div");
  grid.className = "timeline-grid";
  const axis = document.createElement("div");
  axis.className = "timeline-axis";
  // Space date labels by the room available, about 64px each, so a phone
  // gets fewer of them rather than an overlapping row.
  const days = (end - start) / 86_400_000;
  const plotWidth = Math.max(120, container.clientWidth - 80);
  const labelEvery =
    [1, 2, 3, 5, 7, 10, 14].find((step) => days / step <= plotWidth / 64) || 14;
  const midnight = new Date(start);
  midnight.setHours(24, 0, 0, 0);
  for (let day = 0, tick = midnight.getTime(); tick < end; day += 1) {
    const line = document.createElement("i");
    line.style.left = position(tick);
    grid.append(line);
    if (day % labelEvery === 0) {
      const label = document.createElement("span");
      label.style.left = position(tick);
      label.textContent = new Date(tick).toLocaleDateString([], { month: "short", day: "numeric" });
      axis.append(label);
    }
    const next = new Date(tick);
    next.setDate(next.getDate() + 1);
    tick = next.getTime();
  }

  const modeLane = document.createElement("div");
  modeLane.className = "timeline-lane timeline-lane--mode";
  for (const segment of timelineModeSegments(start, end)) {
    const bar = document.createElement("span");
    bar.className = `timeline-segment mode--${segment.mode.mode || "unknown"}`;
    bar.style.left = position(segment.start);
    bar.style.width = `${((segment.end - segment.start) / (end - start)) * 100}%`;
    bar.title = `${modeChipText(segment.mode)}: ${formatDate(new Date(segment.start))} to ${formatDate(new Date(segment.end))}`;
    modeLane.append(bar);
  }

  const eventLane = document.createElement("div");
  eventLane.className = "timeline-lane timeline-lane--events";
  const internetLane = document.createElement("div");
  internetLane.className = "timeline-lane timeline-lane--internet";
  for (const item of visible) {
    const type = TIMELINE_TYPES[item.type];
    if (item.type === "outage") {
      const bar = document.createElement("span");
      bar.className = "timeline-outage";
      bar.dataset.key = item.key;
      bar.style.left = position(item.time);
      bar.style.width = `${((item.end - item.time) / (end - start)) * 100}%`;
      bar.title = `${type.title}, ${formatOutageDuration(item.outage.duration_seconds)}: ${formatDate(new Date(item.time))}`;
      internetLane.append(bar);
      continue;
    }
    const marker = document.createElement("span");
    marker.className = `timeline-event tone--${type.tone}`;
    marker.dataset.key = item.key;
    marker.dataset.time = String(item.time);
    marker.style.left = position(item.time);
    marker.title = `${type.title}: ${formatDate(new Date(item.time))}`;
    marker.append(iconNode(type.icon));
    eventLane.append(marker);
  }

  const cursor = document.createElement("div");
  cursor.className = "timeline-cursor";
  cursor.append(document.createElement("b"));

  plot.append(grid, modeLane, eventLane, internetLane, axis, cursor);
  container.append(labels, plot);
  layoutTimelineIcons();

  const selected =
    visible.find((item) => item.key === state.timelineSelectedKey) ||
    [...visible].reverse().find((item) => item.type !== "outage") ||
    visible[visible.length - 1] ||
    null;
  selectTimelineItem(selected?.key ?? null);
}

// Stack icons that would overlap into up to three rows; beyond that they
// overlap, which only happens with several changes within minutes.
function layoutTimelineIcons() {
  const lane = els.connectionTimeline.querySelector(".timeline-lane--events");
  if (!lane) {
    return;
  }
  const width = lane.clientWidth;
  const rowEnds = [];
  for (const marker of lane.querySelectorAll(".timeline-event")) {
    const left = (parseFloat(marker.style.left) / 100) * width - TIMELINE_ICON_SIZE / 2;
    let row = rowEnds.findIndex((rowEnd) => rowEnd + TIMELINE_ICON_GAP <= left);
    if (row === -1) {
      row = rowEnds.length < TIMELINE_MAX_ROWS
        ? rowEnds.length
        : rowEnds.indexOf(Math.min(...rowEnds));
    }
    rowEnds[row] = left + TIMELINE_ICON_SIZE;
    marker.style.top = `${row * (TIMELINE_ICON_SIZE + 4)}px`;
  }
  lane.style.height = `${Math.max(1, rowEnds.length) * (TIMELINE_ICON_SIZE + 4)}px`;
  const label = els.connectionTimeline.querySelector(".timeline-labels span:nth-child(2)");
  if (label) {
    label.style.height = lane.style.height;
  }
}

function selectTimelineItem(key, { moveCursor = true } = {}) {
  const visible = state.timelineVisible || [];
  const selected = visible.find((item) => item.key === key) || null;
  state.timelineSelectedKey = selected?.key ?? null;
  els.connectionTimeline.querySelectorAll("[data-key]").forEach((node) => {
    node.classList.toggle("is-selected", node.dataset.key === state.timelineSelectedKey);
  });
  if (moveCursor) {
    positionTimelineCursor(selected?.time);
  }
  const index = selected ? visible.indexOf(selected) : -1;
  els.connectionTimeline.setAttribute("aria-valuemin", "0");
  els.connectionTimeline.setAttribute("aria-valuemax", String(Math.max(0, visible.length - 1)));
  els.connectionTimeline.setAttribute("aria-valuenow", String(Math.max(0, index)));
  els.connectionTimeline.setAttribute(
    "aria-valuetext",
    selected
      ? `${TIMELINE_TYPES[selected.type].title}, ${formatDate(new Date(selected.time))}`
      : "No events"
  );
  renderTimelineDetail(selected, index, visible.length);
}

function positionTimelineCursor(time) {
  const cursor = els.connectionTimeline.querySelector(".timeline-cursor");
  const range = state.timelineRange;
  if (!cursor || !range) {
    return;
  }
  cursor.hidden = !Number.isFinite(time);
  if (Number.isFinite(time)) {
    cursor.style.left = `${clamp(((time - range.start) / range.span) * 100, 0, 100)}%`;
  }
}

function stepTimeline(delta) {
  const visible = state.timelineVisible || [];
  if (!visible.length) {
    return;
  }
  const current = visible.findIndex((item) => item.key === state.timelineSelectedKey);
  const next = current === -1
    ? (delta > 0 ? 0 : visible.length - 1)
    : clamp(current + delta, 0, visible.length - 1);
  selectTimelineItem(visible[next].key);
}

// Dragging moves the cursor freely and selects whichever event is nearest in
// time; letting go snaps the cursor onto that event.
function scrubTimeline(clientX, forcedKey) {
  const plot = els.connectionTimeline.querySelector(".timeline-plot");
  const range = state.timelineRange;
  const visible = state.timelineVisible || [];
  if (!plot || !range || !visible.length) {
    return;
  }
  const rect = plot.getBoundingClientRect();
  const ratio = clamp((clientX - rect.left) / rect.width, 0, 1);
  const time = range.start + ratio * range.span;
  let nearest = forcedKey ? visible.find((item) => item.key === forcedKey) : null;
  if (!nearest) {
    nearest = visible.reduce((best, item) =>
      Math.abs(item.time - time) < Math.abs(best.time - time) ? item : best
    );
  }
  positionTimelineCursor(forcedKey ? nearest.time : time);
  if (nearest.key !== state.timelineSelectedKey) {
    selectTimelineItem(nearest.key, { moveCursor: false });
  }
}

function bindTimeline() {
  const timeline = els.connectionTimeline;
  const finish = () => {
    if (!state.timelineDragging) {
      return;
    }
    state.timelineDragging = false;
    timeline.classList.remove("is-dragging");
    const selected = (state.timelineVisible || []).find(
      (item) => item.key === state.timelineSelectedKey
    );
    positionTimelineCursor(selected?.time);
  };
  timeline.addEventListener("pointerdown", (event) => {
    if (!state.timelineVisible?.length || event.button > 0) {
      return;
    }
    state.timelineDragging = true;
    timeline.classList.add("is-dragging");
    timeline.setPointerCapture(event.pointerId);
    timeline.focus({ preventScroll: true });
    scrubTimeline(event.clientX, event.target.closest("[data-key]")?.dataset.key);
  });
  timeline.addEventListener("pointermove", (event) => {
    if (state.timelineDragging) {
      scrubTimeline(event.clientX);
    }
  });
  timeline.addEventListener("pointerup", finish);
  timeline.addEventListener("pointercancel", finish);
  timeline.addEventListener("keydown", (event) => {
    const steps = { ArrowLeft: -1, ArrowRight: 1, ArrowUp: 1, ArrowDown: -1 };
    if (event.key in steps) {
      event.preventDefault();
      stepTimeline(steps[event.key]);
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      stepTimeline(event.key === "Home" ? -Infinity : Infinity);
    }
  });
  if ("ResizeObserver" in window) {
    new ResizeObserver(() => window.requestAnimationFrame(layoutTimelineIcons)).observe(timeline);
  }
}

function renderTimelineFilters(items) {
  const counts = {};
  for (const item of items) {
    counts[item.type] = (counts[item.type] || 0) + 1;
  }
  for (const [type, definition] of Object.entries(TIMELINE_TYPES)) {
    if (!counts[type]) {
      continue;
    }
    const hidden = state.timelineHidden.has(type);
    const button = document.createElement("button");
    button.type = "button";
    button.className = `timeline-filter tone--${definition.tone}`;
    button.setAttribute("aria-pressed", String(!hidden));
    button.title = `${hidden ? "Show" : "Hide"} ${definition.label.toLowerCase()} (${counts[type]})`;
    const count = document.createElement("span");
    count.textContent = String(counts[type]);
    button.append(iconNode(definition.icon), count);
    button.addEventListener("click", () => {
      if (hidden) {
        state.timelineHidden.delete(type);
      } else {
        state.timelineHidden.add(type);
      }
      renderConnectionTimeline();
    });
    els.timelineFilters.append(button);
  }
}

function renderTimelineDetail(item, index, total) {
  const detail = els.timelineDetail;
  replaceChildren(detail);
  const stepButton = (direction, disabled) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "timeline-step";
    button.disabled = disabled;
    button.setAttribute("aria-label", direction < 0 ? "Previous event" : "Next event");
    button.append(iconNode(direction < 0 ? "prev" : "next"));
    button.addEventListener("click", () => stepTimeline(direction));
    return button;
  };

  const body = document.createElement("div");
  body.className = "timeline-detail-body";
  if (!item) {
    body.append(emptyNode("No events in this range."));
    detail.append(stepButton(-1, true), body, stepButton(1, true));
    return;
  }

  const type = TIMELINE_TYPES[item.type];
  const badge = document.createElement("span");
  badge.className = `timeline-detail-icon tone--${type.tone}`;
  badge.append(iconNode(type.icon));

  const header = document.createElement("div");
  header.className = "timeline-detail-header";
  const title = document.createElement("strong");
  title.textContent = type.title;
  const when = document.createElement("span");
  when.textContent = `${formatDate(new Date(item.time))} · ${formatRelative(item.time)}`;
  const position = document.createElement("small");
  position.textContent = `${index + 1} / ${total}`;
  header.append(title, when, position);

  const chips = document.createElement("div");
  chips.className = "timeline-chips";
  chips.append(...timelineChips(item));
  body.append(header, chips);
  detail.append(stepButton(-1, index <= 0), badge, body, stepButton(1, index >= total - 1));
}

function timelineChips(item) {
  const details = item.event?.details || {};
  const arrow = () => {
    const node = document.createElement("span");
    node.className = "timeline-arrow";
    node.textContent = "→";
    return node;
  };
  switch (item.type) {
    case "outage": {
      const outage = item.outage;
      return [
        chip(outage.ongoing ? `${formatOutageDuration(outage.duration_seconds)} so far` : formatOutageDuration(outage.duration_seconds), "red"),
        DIAGNOSIS_SHORT_LABELS[outage.diagnosis]
          ? chip(DIAGNOSIS_SHORT_LABELS[outage.diagnosis])
          : chip("Not diagnosed", "muted"),
      ];
    }
    case "restart":
      return [
        chip(`Up ${formatOutageDuration(details.previous_uptime_seconds)} before`),
        details.requested_by_app
          ? chip("Requested by this app", "muted")
          : chip("Not requested by this app", "magenta"),
      ];
    case "site":
      return [chip(`Site ${details.from?.site ?? "?"}`), arrow(), chip(`Site ${details.to?.site ?? "?"}`), modeChip(details.to)];
    case "sector": {
      const radio = ["nr", "lte"].find(
        (key) => details.from?.cells?.[key]?.cell_id !== details.to?.cells?.[key]?.cell_id
      ) || "nr";
      return [
        chip(`${radio === "nr" ? "5G" : "LTE"} cell ${details.from?.cells?.[radio]?.cell_id ?? "?"}`),
        arrow(),
        chip(`cell ${details.to?.cells?.[radio]?.cell_id ?? "?"}`),
        chip(`Site ${details.to?.site ?? "?"}`, "muted"),
      ];
    }
    case "firmware":
    case "registration":
      return [chip(String(details.from ?? "?")), arrow(), chip(String(details.to ?? "?"))];
    default:
      return [modeChip(details.from), arrow(), modeChip(details.to)];
  }
}

function chip(text, tone = "") {
  const node = document.createElement("span");
  node.className = `timeline-chip${tone ? ` tone--${tone}` : ""}`;
  node.textContent = text;
  return node;
}

function modeChipText(mode) {
  const label = MODE_SHORT_LABELS[mode?.mode] || "Unknown";
  return mode?.bands ? `${label} · ${mode.bands}` : label;
}

function modeChip(mode) {
  const node = chip(modeChipText(mode));
  const dot = document.createElement("i");
  dot.className = `mode-dot mode--${mode?.mode || "unknown"}`;
  node.prepend(dot);
  return node;
}

function formatRelative(time) {
  const minutes = Math.round((Date.now() - time) / 60000);
  if (minutes < 1) {
    return "just now";
  }
  if (minutes < 60) {
    return `${minutes} min ago`;
  }
  const hours = Math.round(minutes / 60);
  if (hours < 48) {
    return `${hours} h ago`;
  }
  return `${Math.round(hours / 24)} days ago`;
}

function renderOutageBreakdown(outages) {
  replaceChildren(els.outageBreakdown);
  const buckets = Array.isArray(outages.duration_buckets) ? outages.duration_buckets : [];
  if (!outages.count) {
    els.outageBreakdown.append(emptyNode("No outages in this range."));
    setText(els.outageDiagnosis, "");
    return;
  }
  const largest = Math.max(1, ...buckets.map((bucket) => bucket.count));
  for (const bucket of buckets) {
    const row = document.createElement("div");
    row.className = "bar-row";
    const label = document.createElement("span");
    label.textContent = bucket.label;
    const track = document.createElement("div");
    track.className = "bar-track";
    const fill = document.createElement("i");
    fill.style.setProperty("--level", String(bucket.count / largest));
    track.append(fill);
    const value = document.createElement("strong");
    value.textContent = String(bucket.count);
    row.append(label, track, value);
    els.outageBreakdown.append(row);
  }

  const notes = [];
  const count = Number(outages.count || 0);
  if (outages.peak_hour_count >= 3 && outages.peak_hour_count / count >= 0.25) {
    notes.push(
      `${outages.peak_hour_count} of ${count} started ${formatHour(outages.peak_hour)}–` +
        `${formatHour((outages.peak_hour + 1) % 24)}, a fixed window that suggests scheduled network work.`
    );
  }
  const diagnoses = Array.isArray(outages.diagnoses) ? outages.diagnoses : [];
  const diagnosed = diagnoses.filter((item) => item.key !== "unknown");
  if (diagnosed.length) {
    notes.push(
      diagnosed
        .map((item) => `${DIAGNOSIS_SHORT_LABELS[item.key] || item.label}: ${item.count}`)
        .join(" · ")
    );
  } else {
    notes.push("New outages record whether the radio was still connected.");
  }
  setText(els.outageDiagnosis, notes.join(" "));
}

function formatHour(hour) {
  return `${String(hour).padStart(2, "0")}:00`;
}

function formatUtcOffset(minutes) {
  const sign = minutes < 0 ? "−" : "+";
  const absolute = Math.abs(minutes);
  const hours = Math.floor(absolute / 60);
  const remainder = absolute % 60;
  return `UTC${sign}${hours}${remainder ? `:${String(remainder).padStart(2, "0")}` : ""}`;
}

function formatOutageDuration(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  if (total < 60) {
    return `${total} s`;
  }
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours >= 48) {
    return `${Math.floor(hours / 24)} d ${hours % 24} h`;
  }
  if (hours) {
    return `${hours} h ${minutes} min`;
  }
  return secs ? `${minutes} min ${secs} s` : `${minutes} min`;
}

function telemetryPointsWithCurrent() {
  const stored = Array.isArray(state.telemetryHistory?.points)
    ? state.telemetryHistory.points.slice()
    : [];
  const current = currentTelemetryPoint();
  if (current) {
    const currentTime = new Date(current.observed_at).getTime();
    const lastTime = stored.length ? new Date(stored[stored.length - 1].observed_at).getTime() : NaN;
    if (!Number.isFinite(lastTime) || Math.abs(currentTime - lastTime) > 1000) {
      stored.push(current);
    }
  }
  return stored
    .filter((point) => Number.isFinite(new Date(point.observed_at).getTime()))
    .sort((left, right) => new Date(left.observed_at) - new Date(right.observed_at));
}

function currentTelemetryPoint() {
  const overview = state.overview;
  if (!overview?.observed_at || overview?.detection?.reachable !== true) {
    return null;
  }
  const radios = {};
  for (const radio of Array.isArray(overview.radios) ? overview.radios : []) {
    const metrics = {};
    for (const metric of Array.isArray(radio.metrics) ? radio.metrics : []) {
      const value = Number(metric.value);
      if (Number.isFinite(value)) {
        metrics[metric.key] = value;
      }
    }
    radios[radio.key] = { metrics };
  }
  return {
    observed_at: overview.observed_at,
    signal_score: overview.signal?.score,
    radios,
    system: {
      temperature_c: overview.system?.temperature?.celsius,
      uptime_seconds: overview.system?.uptime_seconds,
    },
  };
}

function renderLineChart(container, points, seriesDefinitions, options) {
  replaceChildren(container);
  const series = seriesDefinitions
    .map((definition) => ({
      ...definition,
      values: points
        .map((point) => {
          const rawValue = definition.read(point);
          return {
            time: new Date(point.observed_at).getTime(),
            value: isFiniteReading(rawValue) ? Number(rawValue) : NaN,
          };
        })
        .filter((item) => Number.isFinite(item.time) && Number.isFinite(item.value)),
    }))
    .filter((definition) => definition.values.length);
  if (!series.length) {
    container.append(emptyNode(options.emptyText));
    return;
  }

  const legend = document.createElement("div");
  legend.className = "chart-legend";
  for (const definition of series) {
    const item = document.createElement("span");
    item.className = definition.className;
    const marker = document.createElement("i");
    const latest = definition.values[definition.values.length - 1].value;
    const textNode = document.createElement("span");
    textNode.textContent = `${definition.label} ${formatChartNumber(latest, options.decimals)} ${options.unit}`;
    item.append(marker, textNode);
    legend.append(item);
  }

  const width = 720;
  const height = 230;
  const margin = { top: 14, right: 18, bottom: 36, left: 54 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const allValues = series.flatMap((definition) => definition.values.map((item) => item.value));
  const allTimes = series.flatMap((definition) => definition.values.map((item) => item.time));
  let minValue = Math.min(...allValues);
  let maxValue = Math.max(...allValues);
  const valuePadding = Math.max((maxValue - minValue) * 0.12, options.decimals ? 1.5 : 3);
  minValue -= valuePadding;
  maxValue += valuePadding;
  let minTime = Math.min(...allTimes);
  let maxTime = Math.max(...allTimes);
  if (minTime === maxTime) {
    minTime -= 30000;
    maxTime += 30000;
  }
  const x = (time) => margin.left + ((time - minTime) / (maxTime - minTime)) * plotWidth;
  const y = (value) => margin.top + ((maxValue - value) / (maxValue - minValue)) * plotHeight;

  const svg = svgElement("svg", {
    viewBox: `0 0 ${width} ${height}`,
    role: "img",
    "aria-label": `${series.map((item) => item.label).join(" and ")} ${options.unit} history`,
  });
  svg.classList.add("line-chart");
  const title = svgElement("title");
  title.textContent = `${series.map((item) => item.label).join(" and ")} history`;
  svg.append(title);

  for (let index = 0; index <= 4; index += 1) {
    const ratio = index / 4;
    const gridY = margin.top + ratio * plotHeight;
    svg.append(svgElement("line", { x1: margin.left, y1: gridY, x2: width - margin.right, y2: gridY, class: "chart-grid-line" }));
    const label = svgElement("text", { x: margin.left - 9, y: gridY + 4, class: "chart-axis-label", "text-anchor": "end" });
    label.textContent = formatChartNumber(maxValue - ratio * (maxValue - minValue), options.decimals);
    svg.append(label);
  }

  const timeLabels = [minTime, minTime + (maxTime - minTime) / 2, maxTime];
  timeLabels.forEach((time, index) => {
    const label = svgElement("text", {
      x: x(time),
      y: height - 10,
      class: "chart-axis-label",
      "text-anchor": index === 0 ? "start" : index === 2 ? "end" : "middle",
    });
    label.textContent = formatChartTime(time, options.historyHours ?? state.telemetryHours);
    svg.append(label);
  });

  for (const marker of options.markers || []) {
    if (marker.time < minTime || marker.time > maxTime) {
      continue;
    }
    const markerX = x(marker.time);
    const span = { x1: markerX, y1: margin.top, x2: markerX, y2: margin.top + plotHeight };
    const group = svgElement("g", { class: `chart-marker chart-marker--${marker.tone}` });
    const markerTitle = svgElement("title");
    markerTitle.textContent = `${formatDate(new Date(marker.time))}: ${marker.label}`;
    // The visible line is a hairline; a wider transparent twin carries the
    // tooltip so it can actually be hovered.
    group.append(
      markerTitle,
      svgElement("line", { ...span, class: "chart-marker-line" }),
      svgElement("line", { ...span, class: "chart-marker-hit" })
    );
    svg.append(group);
  }

  for (const definition of series) {
    const path = definition.values
      .map((item, index) => `${index ? "L" : "M"} ${x(item.time).toFixed(2)} ${y(item.value).toFixed(2)}`)
      .join(" ");
    const line = svgElement("path", { d: path, class: `chart-series ${definition.className}` });
    svg.append(line);
    const latest = definition.values[definition.values.length - 1];
    const marker = svgElement("circle", {
      cx: x(latest.time),
      cy: y(latest.value),
      r: 4.5,
      class: `chart-latest ${definition.className}`,
    });
    const markerTitle = svgElement("title");
    markerTitle.textContent = `${definition.label}: ${formatChartNumber(latest.value, options.decimals)} ${options.unit}`;
    marker.append(markerTitle);
    svg.append(marker);
  }

  container.append(legend, svg);
}

function svgElement(name, attributes = {}) {
  const element = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attributes)) {
    element.setAttribute(key, String(value));
  }
  return element;
}

function formatChartNumber(value, decimals = 0) {
  return Number(value).toFixed(decimals);
}

function formatChartTime(timestamp, hours) {
  const date = new Date(timestamp);
  if (hours > 24) {
    return date.toLocaleDateString([], { month: "short", day: "numeric" });
  }
  return date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function formatHistoryRange(hours) {
  return hours === 168 ? "7 days" : `${hours} hour${hours === 1 ? "" : "s"}`;
}

function hasDisplayValue(value) {
  return value !== null && value !== undefined && String(value).trim() !== "";
}

function isFiniteReading(value) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}

function renderSignal() {
  const signal = state.overview?.signal || {};
  const score = Number.isFinite(signal.score) ? signal.score : 0;
  const quality = signal.quality || "Unknown";

  els.signalMeter.style.setProperty("--score", String(Math.max(0, Math.min(100, score))));
  els.signalMeter.dataset.rating = toneFromQuality(quality);
  setText(els.signalMeterValue, Number.isFinite(signal.score) ? `${signal.score}%` : "--");
  setText(els.signalMeterLabel, quality);
  setText(els.signalSummary, signal.summary || "Gateway signal metrics are not available.");
  setTag(els.signalStateTag, quality, toneFromQuality(quality));

  replaceChildren(els.signalMetrics);
  const metrics = Array.isArray(signal.metrics) ? signal.metrics : [];
  if (!metrics.length) {
    els.signalMetrics.append(emptyNode("No signal metrics found yet."));
    return;
  }

  for (const metric of metrics) {
    const item = document.createElement("article");
    item.className = `mini-metric mini-metric--${toneFromQuality(metric.rating)}`;

    const label = document.createElement("span");
    label.textContent = metric.label || humanize(metric.key);

    const value = document.createElement("strong");
    value.textContent = metric.display || formatValue(metric.value);

    const source = document.createElement("small");
    source.textContent = metric.source || "";

    item.append(label, value, source);
    els.signalMetrics.append(item);
  }
}

function renderDetails() {
  renderDetailList(els.connectionDetails, state.overview?.connection, "No cellular session data yet.");
  renderDetailList(els.deviceDetails, deviceDetailData(), "No device data yet.");
  renderDetailList(els.wifiDetails, wifiDetailData(), wifiEmptyText());
}

function deviceDetailData() {
  const overviewDevice = state.overview?.device || {};
  const details = state.gatewayDetails;
  if (!details) {
    return overviewDevice;
  }
  const device = details.device || {};
  const sim = details.sim || {};
  const network = details.network || {};
  const clock = details.clock || {};
  let gatewayClock;
  if (clock.timezone) {
    const drift = Number(clock.drift_seconds);
    gatewayClock = Number.isFinite(drift) && Math.abs(drift) >= 60
      ? `${clock.timezone}, ${Math.abs(Math.round(drift / 60))} min ${drift > 0 ? "ahead" : "behind"}`
      : `${clock.timezone}, in sync`;
  }
  return {
    manufacturer: device.manufacturer || overviewDevice.manufacturer,
    model: device.model || overviewDevice.model,
    firmware: device.firmware || overviewDevice.firmware,
    hardware: device.hardware || overviewDevice.hardware,
    api_version: device.api_version,
    serial: device.serial,
    sim_status: sim.status,
    phone_number: sim.phone_number,
    iccid: sim.iccid,
    imei: sim.imei,
    imsi: sim.imsi,
    apn: network.apn,
    ipv6: network.ipv6,
    gateway_clock: gatewayClock,
  };
}

function wifiEmptyText() {
  if (!state.config?.gateway_password_configured) {
    return "Save the gateway login to load Wi-Fi settings.";
  }
  return "No Wi-Fi data returned by the gateway yet.";
}

function wifiDetailData() {
  const overviewWifi = state.overview?.wifi || {};
  const wifi = state.wifi || {};
  return {
    ...overviewWifi,
    ssid: wifi.ssid || overviewWifi.ssid,
    radio_enabled: typeof wifi.radio_enabled === "boolean" ? wifi.radio_enabled : undefined,
    broadcast_enabled:
      typeof wifi.broadcast_enabled === "boolean" ? wifi.broadcast_enabled : undefined,
    clients: state.clients?.count ?? overviewWifi.clients,
  };
}

function renderDetailList(container, data, emptyText) {
  replaceChildren(container);
  const entries = Object.entries(data || {}).filter(([, value]) => hasValue(value));
  if (!entries.length) {
    container.append(emptyNode(emptyText));
    return;
  }

  for (const [key, value] of entries) {
    const row = document.createElement("div");
    row.className = "detail-row";

    const dt = document.createElement("dt");
    dt.textContent = detailLabels[key] || humanize(key);

    const dd = document.createElement("dd");
    dd.textContent = formatValue(value);

    row.append(dt, dd);
    container.append(row);
  }
}

function renderControls() {
  if (state.config) {
    els.dryRunToggle.checked = Boolean(state.config.dry_run);
    els.testFrequency.value = String(state.config.tests_per_hour || 180);
  }
  renderWifiControls();
  renderAdvancedModemControls();

  const source = state.config?.gateway_password_source || "none";
  const configured = Boolean(state.config?.gateway_password_configured);
  if (state.gatewayLoginBusy) {
    setTag(els.gatewayLoginState, "Working", "warn");
  } else if (!configured) {
    setTag(els.gatewayLoginState, "Login needed", "warn");
  } else if (source === "saved") {
    setTag(els.gatewayLoginState, "Saved", "good");
  } else if (source === "environment") {
    setTag(els.gatewayLoginState, "Environment", "info");
  } else if (source === "runtime") {
    setTag(els.gatewayLoginState, "Session", "info");
  } else {
    setTag(els.gatewayLoginState, "Configured", "good");
  }

  updateControlState();
}

function renderAdvancedModemControls() {
  const lab = state.config?.advanced_modem || {};
  if (els.advancedLabEnabled && document.activeElement !== els.advancedLabEnabled) {
    els.advancedLabEnabled.checked = isG4ARLabMode(lab.mode);
  }
  if (els.advancedModemAcknowledge && document.activeElement !== els.advancedModemAcknowledge) {
    els.advancedModemAcknowledge.checked = Boolean(lab.acknowledged);
  }
  if (els.skipStockBackupReminder && document.activeElement !== els.skipStockBackupReminder) {
    els.skipStockBackupReminder.checked = Boolean(lab.skip_stock_backup);
  }
  if (els.advancedUploadProfile && document.activeElement !== els.advancedUploadProfile) {
    els.advancedUploadProfile.value = lab.upload_priority?.profile || "balanced";
  }
  if (els.advancedRadioProfile && document.activeElement !== els.advancedRadioProfile) {
    els.advancedRadioProfile.value = lab.g4ar_radio?.profile || "auto";
  }

  if (!els.advancedModemStatus) {
    return;
  }

  const capabilities = lab.capabilities || {};
  const firmwareLab = lab.g4ar_unlock_lab || lab.g4ar_firmware_lab || {};
  const g4arRadio = lab.g4ar_radio || {};
  renderDetailList(
    els.advancedModemStatus,
    {
      mode: lab.label || "Disabled",
      docker: lab.enabled ? "Connected directly" : "Lab disabled",
      upload_profile: lab.upload_priority?.label || "Balanced",
      radio_profile: g4arRadio.label || "Auto",
      cell_lock: capabilityText(capabilities.cell_lock),
      band_lock: capabilityText(capabilities.band_lock),
      cell_scan: capabilityText(capabilities.cell_scan),
      lte_anchor_override: capabilityText(capabilities.lte_anchor_override),
      radio_mode_override: capabilityText(capabilities.radio_mode_override),
      upload_priority_qos: capabilityText(capabilities.upload_priority_qos),
      stock_firmware_backup: capabilityText(capabilities.stock_firmware_backup),
      custom_firmware_flash: capabilityText(capabilities.custom_firmware_flash),
      root_access: capabilityText(capabilities.root_access),
      tx_power: capabilityText(capabilities.tx_power_override),
    },
    "Advanced modem capabilities load after settings refresh."
  );
  renderDetailList(
    els.firmwareLabStatus,
    {
      device: firmwareLab.device || "Arcadyan TMO-G4AR",
      lab_status: firmwareLab.flash_status || "Select G4AR unlock / radio lab mode",
      radio_goal: g4arRadio.label || "Auto",
      docker_ready: firmwareLab.docker_ready,
      stock_backup_skipped: firmwareLab.stock_backup_skipped,
      required_consent: firmwareLab.consent_phrase,
    },
    "G4AR unlock / radio lab status loads after settings refresh."
  );
  renderFirmwareBackupList();
  renderRootResearch();
}

function renderRootResearch() {
  if (!els.rootResearchTag) {
    return;
  }

  const root =
    state.rootResearch || state.config?.advanced_modem?.g4ar_root_research || {};
  const verified = Boolean(root.verified_root_available);
  setTag(
    els.rootResearchTag,
    verified ? "Verified root path" : "No verified root path",
    verified ? "good" : "bad"
  );
  setText(
    els.rootResearchFinding,
    root.current_finding ||
      "No public, reproducible G4AR root chain has been verified. Read-only research only."
  );
  renderOrderedList(els.rootVerifiedEvidenceList, root.verified_evidence || []);
  renderOrderedList(els.rootUnverifiedList, root.not_verified || []);
  renderOrderedList(
    els.rootResearchPhases,
    (root.research_phases || []).map(
      (phase) => `${phase.title}: ${phase.goal} No writes.`
    )
  );
  renderOrderedList(els.rootHardStopList, root.hard_stops || []);
  if (els.rootConsentPhrase && root.consent_phrase) {
    els.rootConsentPhrase.placeholder = root.consent_phrase;
  }

  const assessment = state.rootResearchAssessment;
  if (!assessment) {
    els.rootAssessmentStatus.className = "inline-status inline-status--muted";
    setText(
      els.rootAssessmentStatus,
      "Assessment has not run. Root execution remains disabled."
    );
    return;
  }

  const readOnlyReady = Boolean(assessment.ready_for_read_only_research);
  els.rootAssessmentStatus.className = `inline-status inline-status--${readOnlyReady ? "warn" : "bad"}`;
  setText(
    els.rootAssessmentStatus,
    readOnlyReady
      ? "Ready for receive-only hardware research. Root execution is still disabled because no verified G4AR chain exists."
      : `Not ready: ${(assessment.missing || []).join("; ")}`
  );
}

function renderFirmwareBackupList() {
  if (!els.firmwareBackupList) {
    return;
  }

  const backups = Array.isArray(state.firmwareBackups?.backups)
    ? state.firmwareBackups.backups
    : [];
  replaceChildren(els.firmwareBackupList);
  const labSaved = isG4ARLabMode(state.config?.advanced_modem?.mode);
  const readinessMessage = !state.config?.gateway_password_configured
    ? "Save and test the gateway login in Step 1 to enable bundle creation."
    : !labSaved
      ? "Enable the owner lab, accept the warning, and save Step 1 first."
      : "Ready to read the stock gateway API and create a recovery bundle.";
  const backupStatus = state.firmwareBackups?.backup_dir
    ? `Saved in ${state.firmwareBackups.backup_dir}. ${readinessMessage}`
    : "Backup history loads after refresh.";
  const skipMessage = labSkipsStockBackup()
    ? "Reminder hidden. A separate verified raw partition backup is still required before flash research."
    : "";
  setText(els.firmwareBackupStatus, compactJoin([backupStatus, skipMessage], " "));

  if (!backups.length) {
    els.firmwareBackupList.append(emptyNode("No Docker recovery bundles saved yet."));
    return;
  }

  for (const backup of backups.slice(0, 5)) {
    const item = document.createElement("article");
    item.className = "backup-item";

    const identity = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = backup.id || "G4AR backup";
    const subtitle = document.createElement("small");
    subtitle.textContent = compactJoin(
      [
        formatDate(backup.created_at),
        backup.firmware_version && `Firmware ${backup.firmware_version}`,
        backup.raw_firmware_included ? "Raw firmware included" : "Stock API bundle",
      ],
      " - "
    );
    identity.append(title, subtitle);

    const count = document.createElement("span");
    count.textContent = `${backup.artifact_count || 0} ${backup.artifact_count === 1 ? "file" : "files"}`;

    const artifacts = document.createElement("p");
    artifacts.className = "backup-artifacts";
    const artifactNames = Array.isArray(backup.artifacts)
      ? backup.artifacts.map((artifact) => artifact.name).filter(Boolean)
      : [];
    artifacts.textContent = artifactNames.length
      ? artifactNames.join(", ")
      : "Recovery manifest saved.";

    const download = document.createElement("a");
    download.className = "button button--secondary backup-download";
    download.href = backup.download_url || `/api/g4ar/firmware/backups/${backup.id}/download`;
    download.textContent = "Download ZIP";

    const limitation = document.createElement("p");
    limitation.className = "backup-limitation";
    limitation.textContent = backup.raw_firmware_included
      ? "Raw firmware reported by this legacy backup. Verify every hash before use."
      : "Does not include raw flash, calibration, identity, or NVRAM partitions.";

    item.append(identity, count, download, artifacts, limitation);
    els.firmwareBackupList.append(item);
  }
}

function capabilityText(capability) {
  if (!capability) {
    return "Unknown";
  }
  if (capability.supported) {
    return capability.status ? `${humanize(capability.status)} - ${capability.reason || "Ready"}` : "Docker ready";
  }
  return capability.status ? `${humanize(capability.status)} - ${capability.reason || "Unavailable"}` : "Unavailable";
}

function isG4ARLabMode(mode) {
  return mode === "g4ar_unlock_lab" || mode === "g4ar_firmware_lab";
}

function labSkipsStockBackup() {
  return Boolean(state.config?.advanced_modem?.skip_stock_backup);
}

function renderWifiControls() {
  const currentSsid = state.wifi?.ssid || state.overview?.wifi?.ssid || "";
  if (document.activeElement !== els.wifiSsid) {
    els.wifiSsid.value = currentSsid;
  }
  if (typeof state.wifi?.radio_enabled === "boolean") {
    els.wifiRadioToggle.checked = state.wifi.radio_enabled;
  } else {
    els.wifiRadioToggle.checked = true;
  }
}

function renderClients() {
  const devices = state.clients?.devices || [];
  const count = state.clients?.count ?? devices.length;
  setTag(els.clientCountTag, `${count} ${count === 1 ? "device" : "devices"}`, count ? "info" : "muted");
  replaceChildren(els.clientTableBody);

  if (!devices.length) {
    addEmptyTableRow(els.clientTableBody, 6, clientsEmptyText());
    return;
  }

  for (const device of devices) {
    const identification = device.identification || {};
    const row = document.createElement("tr");
    row.append(
      tableCell(device.hostname || identification.name || "Unknown device"),
      tableCell(device.ip_address || "Unknown"),
      tableCell(device.mac_address || "Hidden"),
      tableCell(compactJoin([device.interface, device.band || device.ssid], " / ") || "Unknown"),
      tableCell(device.vendor || "Unknown"),
      tableCell(deviceGuessNode(identification))
    );
    els.clientTableBody.append(row);
  }
}

function clientsEmptyText() {
  if (!state.config?.gateway_password_configured) {
    return "Save the gateway login to load connected devices.";
  }
  if (state.clients === null) {
    return "Connected-device data is not available yet.";
  }
  return "The gateway reported no connected devices.";
}

function deviceGuessNode(identification) {
  const wrapper = document.createElement("div");
  wrapper.className = "device-guess";
  const name = document.createElement("strong");
  name.textContent = identification.name || "Unknown device";
  const confidence = document.createElement("small");
  const value = Number(identification.confidence || 0);
  confidence.textContent = `${Math.round(value * 100)}% confidence`;
  wrapper.append(name, confidence);
  return wrapper;
}

function renderTowerMapSummary() {
  const data = state.mapData || {};
  const identity = data.connected?.identity || {};
  const provider = data.provider || {};
  const hasIdentity = Boolean(identity.cell_id || identity.pci || identity.band);
  const providerReady = Boolean(provider.configured);
  const nearbyCount = Array.isArray(data.nearby) ? data.nearby.length : 0;

  setTag(
    els.mapPreviewTag,
    hasIdentity ? "Cell detected" : "No tower ID",
    hasIdentity ? "info" : "muted"
  );
  setTag(
    els.mapProviderTag,
    providerReady
      ? nearbyCount
        ? "OpenCellID active"
        : "OpenCellID ready"
      : "Add OpenCellID key",
    providerReady ? "good" : "warn"
  );
  const advancedModem = state.config?.advanced_modem || {};
  if (advancedModem.enabled) {
    setTag(els.mapTowerLockTag, "Owner lab enabled", "info");
  } else {
    setTag(els.mapTowerLockTag, "Tower lock unsupported", "warn");
  }
  setTag(
    els.nearbyTowerCountTag,
    `${nearbyCount} ${nearbyCount === 1 ? "tower" : "towers"}`,
    nearbyCount ? "info" : "muted"
  );

  renderMapInputs(data);
  renderTowerIdentityDetails(data);
  renderNearbyTowers(data);
  renderMapStatus(data);
  renderMaps(data);
}

function renderMapInputs(data) {
  const mapConfig = state.config?.map || {};
  const center = data.map?.center || {};
  const editableLatitude =
    mapConfig.latitude ?? (center.source !== "default_us" ? center.latitude : "");
  const editableLongitude =
    mapConfig.longitude ?? (center.source !== "default_us" ? center.longitude : "");
  const radius = mapConfig.radius_km ?? data.map?.radius_km ?? DEFAULT_MAP_RADIUS_KM;

  if (document.activeElement !== els.mapLatitude) {
    els.mapLatitude.value = hasValue(editableLatitude) ? String(editableLatitude) : "";
  }
  if (document.activeElement !== els.mapLongitude) {
    els.mapLongitude.value = hasValue(editableLongitude) ? String(editableLongitude) : "";
  }
  if (document.activeElement !== els.mapRadius) {
    els.mapRadius.value = String(radius);
  }
}

function renderTowerIdentityDetails(data) {
  const identity = data.connected?.identity || {};
  const location = data.connected?.location || null;
  const details = {
    operator: identity.operator,
    radio: identity.radio,
    network_type: identity.network_type,
    band: identity.band,
    pci: identity.pci,
    cell_id: identity.cell_id,
    lac: identity.lac,
    mcc: identity.mcc,
    mnc: identity.mnc,
    tower_distance:
      location && Number.isFinite(location.distance_km)
        ? `${location.distance_km} km`
        : undefined,
    tower_accuracy:
      location && location.range_m ? `${location.range_m} m` : undefined,
    tower_match: location?.match_confidence,
    tower_match_note: location?.match_note,
  };
  renderDetailList(
    els.towerIdentityDetails,
    details,
    "No serving-cell identity has been reported by the gateway yet."
  );
  renderDetailList(
    els.mapPreviewDetails,
    {
      radio: identity.radio,
      band: identity.band,
      pci: identity.pci,
      cell_id: identity.cell_id,
    },
    "Open Map to configure a center and tower data source."
  );
}

function renderNearbyTowers(data) {
  replaceChildren(els.nearbyTowerTableBody);
  const towers = data.nearby || [];
  if (!towers.length) {
    let message = "Save an OpenCellID API key in Settings to load nearby tower records.";
    if (data.provider?.nearby_loaded) {
      message = "OpenCellID found no nearby tower records around this map center.";
    } else if (data.provider?.configured) {
      message = "No nearby tower records loaded yet. Refresh Towers to query OpenCellID.";
    }
    addEmptyTableRow(els.nearbyTowerTableBody, 6, message);
    return;
  }

  for (const tower of towers) {
    const row = document.createElement("tr");
    row.append(
      tableCell(tower.label || "Cell tower"),
      tableCell(tower.radio || "Unknown"),
      tableCell(formatDistance(tower.distance_km)),
      tableCell(formatSignal(tower.average_signal)),
      tableCell(tower.range_m ? `${tower.range_m} m` : "Unknown"),
      tableCell(tower.samples ?? "Unknown")
    );
    els.nearbyTowerTableBody.append(row);
  }
}

function renderMapStatus(data) {
  const errors = data.errors || [];
  const notices = data.notices || [];
  if (errors.length) {
    setMapStatus(errors.join(" | "), "error");
    return;
  }
  if (notices.length) {
    setMapStatus(notices.join(" "), "warn");
    return;
  }
  if (!data.provider?.configured) {
    setMapStatus("OpenCellID key is optional, but needed for real tower locations.", "");
    return;
  }
  if (state.mapBusy) {
    setMapStatus("Refreshing tower map.", "");
    return;
  }
  if (data.location?.center_source === "public_ip" && data.location?.auto_detected) {
    const location = data.location.auto_detected;
    const place = compactJoin([location.city, location.region, location.country], ", ");
    setMapStatus(
      place
        ? `Map centered from public IP estimate near ${place}.`
        : "Map centered from public IP estimate.",
      "info"
    );
    return;
  }
  setMapStatus(data.provider?.nearby_loaded ? "Tower map refreshed." : "", "success");
}

function renderMaps(data) {
  renderLeafletMap("preview", els.dashboardMapPreview, data, { preview: true });
  if (isMapViewVisible()) {
    renderLeafletMap("main", els.towerMap, data, { preview: false });
  }
}

function renderLeafletMap(key, container, data, { preview }) {
  if (!container) {
    return;
  }
  if (!window.L) {
    container.textContent = "Map library is loading.";
    return;
  }
  if (!preview && !isElementRenderable(container)) {
    scheduleMainMapRender(120);
    return;
  }

  const map = ensureLeafletMap(key, container, { preview });
  if (!map) {
    return;
  }

  const layerKey = key === "preview" ? "previewLayer" : "mainLayer";
  if (state.maps[layerKey]) {
    state.maps[layerKey].remove();
  }

  const layer = window.L.layerGroup().addTo(map);
  state.maps[layerKey] = layer;

  const center = mapCenter(data);
  const points = [];
  const home = data.home;
  const connectedTower = data.connected?.location;

  if (home) {
    const position = [home.latitude, home.longitude];
    points.push(position);
    window.L.circleMarker(position, {
      radius: preview ? 7 : 8,
      color: "#2563eb",
      weight: 2,
      fillColor: "#2563eb",
      fillOpacity: 0.78,
    })
      .bindPopup("Saved gateway location")
      .addTo(layer);
  }

  if (connectedTower) {
    const position = [connectedTower.latitude, connectedTower.longitude];
    points.push(position);
    window.L.circleMarker(position, {
      radius: preview ? 9 : 10,
      color: "#e20074",
      weight: 3,
      fillColor: "#e20074",
      fillOpacity: 0.82,
    })
      .bindPopup(towerPopup(connectedTower, "Serving tower"))
      .bindTooltip("Serving tower", {
        direction: "top",
        offset: [0, -8],
        permanent: !preview,
        className: "tower-tooltip tower-tooltip--connected",
      })
      .addTo(layer);

    if (connectedTower.range_m && !preview) {
      window.L.circle(position, {
        radius: connectedTower.range_m,
        color: "#e20074",
        fillColor: "#e20074",
        fillOpacity: 0.08,
        weight: 1,
      }).addTo(layer);
    }
  }

  if (!preview) {
    for (const tower of data.nearby || []) {
      if (!Number.isFinite(tower.latitude) || !Number.isFinite(tower.longitude)) {
        continue;
      }
      const position = [tower.latitude, tower.longitude];
      const isConnected = connectedTower && tower.id === connectedTower.id;
      if (isConnected) {
        continue;
      }
      points.push(position);
      window.L.circleMarker(position, {
        radius: isConnected ? 10 : 7,
        color: isConnected ? "#e20074" : "#0f766e",
        weight: isConnected ? 3 : 2,
        fillColor: isConnected ? "#e20074" : "#0f766e",
        fillOpacity: isConnected ? 0.82 : 0.66,
      })
        .bindPopup(towerPopup(tower, isConnected ? "Connected tower" : "Nearby tower"))
        .addTo(layer);
    }
  }

  if (home && connectedTower && !preview) {
    window.L.polyline(
      [
        [home.latitude, home.longitude],
        [connectedTower.latitude, connectedTower.longitude],
      ],
      {
        color: "#e20074",
        weight: 2,
        dashArray: "6 6",
      }
    ).addTo(layer);
  }

  if (!points.length) {
    points.push([center.latitude, center.longitude]);
    window.L.circleMarker(points[0], {
      radius: preview ? 7 : 8,
      color: "#64748b",
      weight: 2,
      fillColor: "#64748b",
      fillOpacity: 0.72,
    })
      .bindPopup("Map center")
      .addTo(layer);
  }

  if (points.length > 1 && !preview) {
    map.fitBounds(window.L.latLngBounds(points), { padding: [28, 28], maxZoom: 14 });
  } else {
    map.setView(points[0], center.source === "default_us" ? 4 : preview ? 11 : 12);
  }
  window.setTimeout(() => map.invalidateSize(), 0);
}

function scheduleMainMapRender(delay = 0) {
  window.setTimeout(() => {
    window.requestAnimationFrame(() => {
      if (!isMapViewVisible()) {
        return;
      }
      renderLeafletMap("main", els.towerMap, mapRenderData(), { preview: false });
      invalidateMaps();
      window.setTimeout(() => {
        renderLeafletMap("main", els.towerMap, mapRenderData(), { preview: false });
        invalidateMaps();
      }, 180);
    });
  }, delay);
}

function mapRenderData() {
  if (state.mapData) {
    return state.mapData;
  }
  const latitude = Number.parseFloat(els.mapLatitude?.value || "");
  const longitude = Number.parseFloat(els.mapLongitude?.value || "");
  const hasInputCenter = Number.isFinite(latitude) && Number.isFinite(longitude);
  const center = hasInputCenter
    ? { latitude, longitude, source: "form" }
    : { ...DEFAULT_MAP_CENTER, source: "default_us" };
  return {
    map: {
      center,
      radius_km: DEFAULT_MAP_RADIUS_KM,
    },
    home: hasInputCenter ? { latitude, longitude, source: "form" } : null,
    connected: { identity: {}, location: null },
    nearby: [],
    provider: {},
    errors: [],
    notices: [],
  };
}

function ensureLeafletMap(key, container, { preview }) {
  if (state.maps[key]) {
    return state.maps[key];
  }

  try {
    const map = window.L.map(container, {
      attributionControl: true,
      zoomControl: !preview,
      dragging: !preview,
      scrollWheelZoom: !preview,
      doubleClickZoom: !preview,
      boxZoom: !preview,
      keyboard: !preview,
      tap: !preview,
    });
    window.L.tileLayer(MAP_TILE_URL, {
      maxZoom: 19,
      attribution: "&copy; OpenStreetMap contributors",
    }).addTo(map);
    if (!preview) {
      window.L.control.scale({ imperial: true, metric: true }).addTo(map);
    }
    state.maps[key] = map;
    return map;
  } catch (error) {
    container.textContent = `Map could not initialize: ${error.message}`;
    return null;
  }
}

function isMapViewVisible() {
  const panel = document.querySelector('[data-view-panel="map"]');
  return Boolean(panel?.classList.contains("is-active") && isElementRenderable(els.towerMap));
}

function isElementRenderable(element) {
  if (!element) {
    return false;
  }
  const box = element.getBoundingClientRect();
  return box.width > 0 && box.height > 0;
}

function mapCenter(data) {
  const center = data?.map?.center || DEFAULT_MAP_CENTER;
  return {
    latitude: Number.isFinite(center.latitude) ? center.latitude : DEFAULT_MAP_CENTER.latitude,
    longitude: Number.isFinite(center.longitude)
      ? center.longitude
      : DEFAULT_MAP_CENTER.longitude,
    source: center.source || "default_us",
  };
}

function invalidateMaps() {
  for (const map of [state.maps.preview, state.maps.main]) {
    if (map) {
      window.setTimeout(() => map.invalidateSize(), 0);
    }
  }
}

function towerPopup(tower, title) {
  return `
    <strong>${escapeHtml(title)}</strong><br>
    ${escapeHtml(tower.label || "Cell tower")}<br>
    Distance: ${escapeHtml(formatDistance(tower.distance_km))}<br>
    Signal: ${escapeHtml(formatSignal(tower.average_signal))}<br>
    Accuracy: ${escapeHtml(tower.range_m ? `${tower.range_m} m` : "Unknown")}
  `;
}

async function refreshTowerMap({ includeNearby = false, quiet = false, force = false } = {}) {
  if (state.mapBusy && !force) {
    return;
  }
  const ownsBusyState = !state.mapBusy;
  if (ownsBusyState) {
    state.mapBusy = true;
    updateControlState();
  }
  if (!quiet) {
    setMapStatus(includeNearby ? "Refreshing tower data." : "Refreshing map.", "");
  }

  const params = new URLSearchParams({
    include_nearby: includeNearby ? "true" : "false",
  });
  const latitude = Number.parseFloat(els.mapLatitude.value);
  const longitude = Number.parseFloat(els.mapLongitude.value);
  const radiusKm = Number.parseFloat(els.mapRadius.value);
  if (Number.isFinite(latitude) && Number.isFinite(longitude)) {
    params.set("latitude", String(latitude));
    params.set("longitude", String(longitude));
  }
  if (Number.isFinite(radiusKm)) {
    params.set("radius_km", String(radiusKm));
  }

  try {
    state.mapData = await api(`/api/gateway/map?${params.toString()}`);
    renderTowerMapSummary();
  } catch (error) {
    setMapStatus(error.message, "error");
  } finally {
    if (ownsBusyState) {
      state.mapBusy = false;
      updateControlState();
    }
    renderTowerMapSummary();
  }
}

async function useBrowserLocation() {
  if (!navigator.geolocation) {
    setMapStatus("Browser location is not available in this browser.", "error");
    return;
  }

  state.mapBusy = true;
  updateControlState();
  setMapStatus("Requesting browser location.", "");

  try {
    const position = await new Promise((resolve, reject) => {
      navigator.geolocation.getCurrentPosition(resolve, reject, {
        enableHighAccuracy: true,
        timeout: 15000,
        maximumAge: 60000,
      });
    });
    els.mapLatitude.value = position.coords.latitude.toFixed(6);
    els.mapLongitude.value = position.coords.longitude.toFixed(6);
    await saveMapCenter({ quiet: true });
    setMapStatus("Browser location saved as the map center.", "success");
  } catch (error) {
    setMapStatus(error.message || "Browser location was not allowed.", "error");
  } finally {
    state.mapBusy = false;
    updateControlState();
  }
}

async function useGatewayLocation() {
  state.mapBusy = true;
  updateControlState();
  setMapStatus("Reading the location the gateway reports.", "");

  try {
    const location = await api("/api/gateway/location");
    const latitude = Number(location.latitude);
    const longitude = Number(location.longitude);
    if (!Number.isFinite(latitude) || !Number.isFinite(longitude)) {
      throw new Error("The gateway returned an unusable location.");
    }
    els.mapLatitude.value = latitude.toFixed(6);
    els.mapLongitude.value = longitude.toFixed(6);
    setMapStatus(
      "Filled in the location the gateway reports. Select Save Map Center to keep it.",
      "success",
    );
  } catch (error) {
    setMapStatus(error.message || "The gateway did not report a location.", "error");
  } finally {
    state.mapBusy = false;
    updateControlState();
  }
}

async function saveMapCenter({ quiet = false } = {}) {
  const latitude = Number.parseFloat(els.mapLatitude.value);
  const longitude = Number.parseFloat(els.mapLongitude.value);
  const radiusKm = Number.parseFloat(els.mapRadius.value);

  if (!Number.isFinite(latitude) || latitude < -90 || latitude > 90) {
    setMapStatus("Latitude must be between -90 and 90.", "error");
    els.mapLatitude.focus();
    return;
  }
  if (!Number.isFinite(longitude) || longitude < -180 || longitude > 180) {
    setMapStatus("Longitude must be between -180 and 180.", "error");
    els.mapLongitude.focus();
    return;
  }
  if (!Number.isFinite(radiusKm) || radiusKm < 0.25 || radiusKm > 100) {
    setMapStatus("Radius must be between 0.25 and 100 km.", "error");
    els.mapRadius.focus();
    return;
  }

  await runMapAction(quiet ? "" : "Saving map center.", async () => {
    state.config = await api("/api/map/settings", {
      method: "POST",
      body: {
        latitude,
        longitude,
        radius_km: radiusKm,
      },
    });
    await refreshTowerMap({ includeNearby: true, quiet: true, force: true });
    return "Map center saved.";
  });
}

async function saveOpenCellIdKey() {
  const key = els.openCellIdKey.value.trim();
  if (!key) {
    setActionMessage("Enter an OpenCellID API key first.", "error");
    els.openCellIdKey.focus();
    return;
  }

  await runAction("Saving OpenCellID key.", async () => {
    state.config = await api("/api/map/settings", {
      method: "POST",
      body: { opencellid_api_key: key },
    });
    els.openCellIdKey.value = "";
    await refreshTowerMap({ includeNearby: true, quiet: true });
    return "OpenCellID key saved.";
  });
}

async function clearOpenCellIdKey() {
  if (!window.confirm("Clear the saved OpenCellID API key?")) {
    return;
  }

  await runAction("Clearing OpenCellID key.", async () => {
    state.config = await api("/api/map/settings", {
      method: "POST",
      body: { clear_opencellid_api_key: true },
    });
    els.openCellIdKey.value = "";
    await refreshTowerMap({ includeNearby: false, quiet: true });
    return "OpenCellID key cleared.";
  });
}

async function runMapAction(workingMessage, action) {
  state.mapBusy = true;
  updateControlState();
  if (workingMessage) {
    setMapStatus(workingMessage, "");
  }
  try {
    const message = await action();
    if (message) {
      setMapStatus(message, "success");
    }
  } catch (error) {
    setMapStatus(error.message, "error");
  } finally {
    state.mapBusy = false;
    updateControlState();
  }
}

function setMapStatus(message, tone) {
  setText(els.mapStatusMessage, message || "");
  els.mapStatusMessage.className = "message";
  if (tone) {
    els.mapStatusMessage.classList.add(`message--${tone}`);
  }
}

function toggleAiming() {
  if (state.aimTimer) {
    // Record that the pause was deliberate. Leaving and re-entering the view
    // calls stopAiming()/startAiming() on its own, and without this flag that
    // would silently undo an explicit Stop.
    state.aimPaused = true;
    stopAiming();
    setAimStatus("Paused. Select Start Aiming to resume.", "");
  } else {
    state.aimPaused = false;
    startAiming();
  }
}

function startAiming() {
  if (state.aimTimer) {
    return;
  }
  state.aimErrors = 0;
  state.aimTimer = window.setInterval(pollAimSignal, AIM_POLL_INTERVAL_MS);
  setText(els.aimToggleButton, "Stop Aiming");
  setTag(els.aimStateTag, "Live", "good");
  setAimStatus("", "");
  pollAimSignal();
}

function stopAiming() {
  if (state.aimTimer) {
    window.clearInterval(state.aimTimer);
    state.aimTimer = null;
  }
  setText(els.aimToggleButton, "Start Aiming");
  setTag(els.aimStateTag, "Paused", "muted");
}

async function pollAimSignal() {
  // The timer is stopped on hide and on leaving the view, so this is only a
  // guard against a poll already in flight when either happens.
  if (document.hidden || state.activeView !== "aim") {
    return;
  }

  try {
    const snapshot = await api("/api/gateway/signal");
    state.aimSnapshot = snapshot;
    state.aimErrors = 0;
    recordAimSample(snapshot);
    renderAim();
    setAimStatus("", "");
  } catch (error) {
    state.aimErrors += 1;
    setAimStatus(error.message || "The gateway did not return a signal reading.", "error");
    if (state.aimErrors >= AIM_MAX_CONSECUTIVE_ERRORS) {
      // Stop rather than keep hammering a gateway that is not answering.
      stopAiming();
      setAimStatus(
        `Stopped after ${AIM_MAX_CONSECUTIVE_ERRORS} failed reads. Select Start Aiming to retry.`,
        "error",
      );
    }
  }
}

function aimMetricRows(snapshot) {
  const rows = [];
  for (const radio of snapshot?.radios || []) {
    for (const metric of radio.metrics || []) {
      rows.push({ radio, metric });
    }
  }
  return rows;
}

function recordAimSample(snapshot) {
  for (const { radio, metric } of aimMetricRows(snapshot)) {
    if (!Number.isFinite(metric.value)) {
      continue;
    }
    const key = `${radio.key}:${metric.key}`;
    const entry = state.aimTrend[key] || {
      label: `${radio.label} ${metric.label || humanize(metric.key)}`,
      unit: metric.unit || "",
      best: metric.value,
      worst: metric.value,
      samples: 0,
    };
    // Every metric here reads better as it rises, so best is simply the maximum.
    entry.current = metric.value;
    entry.best = Math.max(entry.best, metric.value);
    entry.worst = Math.min(entry.worst, metric.value);
    entry.samples += 1;
    state.aimTrend[key] = entry;
  }
}

function resetAimSession() {
  state.aimTrend = {};
  renderAimTrend();
  setAimStatus("Session reset. Best and worst start again from the next reading.", "success");
}

function formatAimNumber(value, unit) {
  if (!Number.isFinite(value)) {
    return "--";
  }
  const rounded = Math.round(value * 10) / 10;
  return unit ? `${rounded} ${unit}` : String(rounded);
}

function renderAim() {
  const snapshot = state.aimSnapshot;
  if (!snapshot) {
    return;
  }

  const signal = snapshot.signal || {};
  const score = Number.isFinite(signal.score) ? signal.score : 0;
  const quality = signal.quality || "Unknown";

  els.aimMeter.style.setProperty("--score", String(Math.max(0, Math.min(100, score))));
  els.aimMeter.dataset.rating = toneFromQuality(quality);
  setText(els.aimMeterValue, Number.isFinite(signal.score) ? `${signal.score}%` : "--");
  setText(els.aimMeterLabel, quality);
  setText(
    els.aimSummary,
    "Move or rotate the gateway and watch these values respond. Readings update every 2 seconds.",
  );

  const observed = new Date(snapshot.observed_at);
  setTag(
    els.aimUpdatedTag,
    Number.isNaN(observed.getTime()) ? "Updated" : `Updated ${observed.toLocaleTimeString()}`,
    "muted",
  );

  replaceChildren(els.aimMetrics);
  const rows = aimMetricRows(snapshot);
  if (!rows.length) {
    els.aimMetrics.append(emptyNode("The gateway returned no signal metrics."));
  } else {
    for (const { radio, metric } of rows) {
      const item = document.createElement("article");
      item.className = `mini-metric mini-metric--${toneFromQuality(metric.rating)}`;

      const label = document.createElement("span");
      label.textContent = `${radio.label} ${metric.label || humanize(metric.key)}`;

      const value = document.createElement("strong");
      value.textContent = metric.display || formatValue(metric.value);

      const note = document.createElement("small");
      note.textContent = metric.rating ? humanize(metric.rating) : "";

      item.append(label, value, note);
      els.aimMetrics.append(item);
    }
  }

  renderAimTrend();
}

function renderAimTrend() {
  replaceChildren(els.aimTrend);
  const keys = Object.keys(state.aimTrend);
  if (!keys.length) {
    els.aimTrend.append(emptyNode("Best and worst readings appear once sampling starts."));
    return;
  }

  for (const key of keys) {
    const entry = state.aimTrend[key];
    const item = document.createElement("article");
    item.className = "mini-metric";

    const label = document.createElement("span");
    label.textContent = `${entry.label} best`;

    const value = document.createElement("strong");
    value.textContent = formatAimNumber(entry.best, entry.unit);

    const note = document.createElement("small");
    note.textContent =
      `now ${formatAimNumber(entry.current, entry.unit)} \u00b7 ` +
      `worst ${formatAimNumber(entry.worst, entry.unit)} \u00b7 ` +
      `${entry.samples} sample${entry.samples === 1 ? "" : "s"}`;

    item.append(label, value, note);
    els.aimTrend.append(item);
  }
}

function setAimStatus(message, tone) {
  setText(els.aimStatusMessage, message || "");
  els.aimStatusMessage.className = "message";
  if (tone) {
    els.aimStatusMessage.classList.add(`message--${tone}`);
  }
}

function renderProbes() {
  replaceChildren(els.probeTableBody);
  const probes = state.status?.last_probe_results || [];
  if (!probes.length) {
    addEmptyTableRow(els.probeTableBody, 4, "No probe results yet.");
    return;
  }

  for (const probe of probes) {
    const row = document.createElement("tr");
    row.append(
      tableCell(cleanUrl(probe.url)),
      tableCell(statusBadge(probe.success, probe.status_code)),
      tableCell(formatLatency(probe.latency_ms)),
      tableCell(probe.error || probe.status_code || "OK")
    );
    els.probeTableBody.append(row);
  }
}

function renderEvents() {
  replaceChildren(els.eventsList);
  if (!state.events.length) {
    els.eventsList.append(emptyNode("No events recorded yet."));
    return;
  }

  for (const event of state.events) {
    const item = document.createElement("article");
    item.className = "event-item";

    const header = document.createElement("div");
    const kind = document.createElement("strong");
    kind.textContent = humanize(event.kind || "event");
    const time = document.createElement("span");
    time.textContent = formatDate(event.timestamp) || "";
    header.append(kind, time);

    const message = document.createElement("p");
    message.textContent = event.message || "";

    item.append(header, message);
    els.eventsList.append(item);
  }
}

function renderGatewaySections() {
  replaceChildren(els.gatewaySections);
  const sections = state.overview?.sections || [];
  if (!sections.length) {
    els.gatewaySections.append(emptyNode("No gateway data sections yet."));
    return;
  }

  for (const section of sections) {
    const details = document.createElement("details");
    details.className = "gateway-data";

    const summary = document.createElement("summary");
    const title = document.createElement("strong");
    title.textContent = section.title || humanize(section.key);
    const count = document.createElement("span");
    count.textContent = `${section.items?.length || 0} fields`;
    summary.append(title, count);
    details.append(summary);

    const list = document.createElement("dl");
    list.className = "gateway-data-list";
    for (const item of section.items || []) {
      const row = document.createElement("div");
      row.className = "detail-row";
      const dt = document.createElement("dt");
      dt.textContent = item.label || "Value";
      const dd = document.createElement("dd");
      dd.textContent = item.value || "";
      row.append(dt, dd);
      list.append(row);
    }
    details.append(list);
    els.gatewaySections.append(details);
  }
}

async function runCheck() {
  await runAction("Running connectivity check.", async () => {
    state.status = await api("/api/check", { method: "POST" });
    await refreshGatewayAndEvents();
    renderAll();
    return "Connectivity check complete.";
  });
}

async function runGatewayTest() {
  const password = els.gatewayPassword.value;
  const configured = Boolean(state.config?.gateway_password_configured);
  if (!configured && !password) {
    setActionMessage("Enter the gateway admin password or save a login first.", "error");
    els.gatewayPassword.focus();
    return;
  }

  await runAction("Testing gateway login.", async () => {
    const result = await api("/api/gateway/test", {
      method: "POST",
      body: password ? { gateway_password: password } : {},
    });
    await refreshGatewayAndEvents();
    if (result.authenticated) {
      return "Gateway is reachable and the login worked.";
    }
    if (result.reachable) {
      return result.message || "Gateway is reachable, but login was not verified.";
    }
    return "Gateway local API was not reachable.";
  });
}

async function saveGatewayLogin() {
  const password = els.gatewayPassword.value;
  if (!password) {
    setActionMessage("Enter the gateway admin password first.", "error");
    els.gatewayPassword.focus();
    return;
  }

  state.gatewayLoginBusy = true;
  await runAction("Saving gateway login.", async () => {
    const result = await api("/api/gateway/login", {
      method: "POST",
      body: {
        gateway_password: password,
        remember: els.rememberPassword.checked,
      },
    });
    state.config = {
      ...(state.config || {}),
      gateway_password_configured: result.gateway_password_configured,
      gateway_password_source: result.gateway_password_source,
      gateway_login_saved: result.gateway_password_source === "saved",
    };
    els.gatewayPassword.value = "";
    await refreshGatewayAndEvents();
    return result.saved ? "Gateway login saved." : "Gateway login active for this session.";
  });
  state.gatewayLoginBusy = false;
  renderControls();
}

async function clearGatewayLogin() {
  if (!window.confirm("Forget the saved gateway login?")) {
    return;
  }

  state.gatewayLoginBusy = true;
  await runAction("Clearing gateway login.", async () => {
    const result = await api("/api/gateway/login", { method: "DELETE" });
    state.config = {
      ...(state.config || {}),
      gateway_password_configured: result.gateway_password_configured,
      gateway_password_source: result.gateway_password_source,
      gateway_login_saved: false,
    };
    els.gatewayPassword.value = "";
    return result.gateway_password_source === "environment"
      ? "Saved login cleared. Environment password remains active."
      : "Gateway login cleared.";
  });
  state.gatewayLoginBusy = false;
  renderControls();
}

async function saveWifiSettings() {
  const ssid = els.wifiSsid.value.trim();
  const radioEnabled = els.wifiRadioToggle.checked;

  if (!state.config?.gateway_password_configured) {
    activateView("settings", { refreshMap: false });
    setActionMessage("Save the gateway admin password in Settings before changing Wi-Fi settings.", "error");
    els.gatewayPassword.focus();
    return;
  }
  if (ssid.length < 1 || ssid.length > 32) {
    setActionMessage("SSID must be between 1 and 32 characters.", "error");
    els.wifiSsid.focus();
    return;
  }
  if (!radioEnabled && !window.confirm("Turn off the gateway Wi-Fi radios?")) {
    return;
  }

  await runAction("Applying Wi-Fi settings.", async () => {
    const result = await api("/api/gateway/wifi", {
      method: "POST",
      body: {
        ssid,
        radio_enabled: radioEnabled,
      },
    });
    state.wifi = result.wifi;
    await refreshGatewayAndEvents();
    renderAll();
    return radioEnabled
      ? "Wi-Fi settings applied."
      : "Gateway Wi-Fi radios disabled.";
  });
}

async function refreshClients(onlineLookup) {
  await runAction(
    onlineLookup ? "Running reverse vendor lookup." : "Refreshing connected devices.",
    async () => {
      state.clients = await api(`/api/gateway/clients?online_lookup=${onlineLookup ? "true" : "false"}`);
      renderDetails();
      renderClients();
      return onlineLookup
        ? "Connected devices refreshed with vendor lookup."
        : "Connected devices refreshed.";
    }
  );
}

async function saveAdvancedModemSettings() {
  const mode = els.advancedLabEnabled.checked ? "g4ar_unlock_lab" : "disabled";
  const acknowledged = els.advancedModemAcknowledge.checked;

  if (mode !== "disabled" && !acknowledged) {
    setActionMessage("Acknowledge the custom firmware and RF compliance warning first.", "error");
    els.advancedModemAcknowledge.focus();
    return;
  }

  await runAction("Saving advanced modem lab settings.", async () => {
    state.config = await api("/api/advanced-modem/settings", {
      method: "POST",
      body: {
        mode,
        acknowledged,
        upload_profile: els.advancedUploadProfile.value,
        radio_profile: els.advancedRadioProfile.value,
        skip_stock_backup: els.skipStockBackupReminder.checked,
      },
    });
    renderAll();
    return mode === "disabled"
      ? "G4AR Docker lab disabled."
      : "G4AR Docker lab settings saved.";
  });
}

async function armG4ARFlashGate() {
  if (!els.advancedLabEnabled.checked) {
    setActionMessage("Enable and save the G4AR Docker lab before opening the flash gate.", "error");
    els.advancedLabEnabled.focus();
    return;
  }

  await runAction("Validating G4AR override consent gate.", async () => {
    await api("/api/g4ar/firmware/flash", {
      method: "POST",
      body: {
        stock_backup_sha256: els.firmwareBackupSha256.value.trim(),
        firmware_sha256: els.firmwareSha256.value.trim(),
        consent_phrase: els.firmwareConsentPhrase.value.trim(),
        backup_verified: els.firmwareBackupVerified.checked,
        recovery_verified: els.firmwareRecoveryVerified.checked,
        understands_brick_risk: els.firmwareUnderstandsRisk.checked,
      },
    });
    return "G4AR override gate validated.";
  });
}

async function assessG4ARRootReadiness() {
  await runAction("Assessing owner G4AR root-research readiness.", async () => {
    state.rootResearchAssessment = await api("/api/g4ar/root/assess", {
      method: "POST",
      body: {
        owns_hardware: els.rootOwnsHardware.checked,
        not_leased_or_financed: els.rootNotLeased.checked,
        spare_noncritical_unit: els.rootSpareUnit.checked,
        hardware_revision_recorded: els.rootRevisionRecorded.checked,
        uart_voltage_verified: els.rootUartVoltageVerified.checked,
        read_only_boot_log_captured: els.rootBootLogCaptured.checked,
        full_backup_verified: els.rootFullBackupVerified.checked,
        offline_recovery_verified: els.rootOfflineRecoveryVerified.checked,
        accepts_permanent_brick_risk: els.rootAcceptsBrickRisk.checked,
        consent_phrase: els.rootConsentPhrase.value.trim(),
      },
    });
    renderRootResearch();
    return state.rootResearchAssessment.ready_for_read_only_research
      ? "Read-only research readiness confirmed. Root execution remains disabled."
      : `Root research is blocked by ${state.rootResearchAssessment.missing.length} requirement(s).`;
  });
}

async function createG4ARFirmwareBackup() {
  if (!els.advancedLabEnabled.checked) {
    setActionMessage("Enable and save the G4AR Docker lab before creating a recovery bundle.", "error");
    els.advancedLabEnabled.focus();
    return;
  }
  if (!els.advancedModemAcknowledge.checked) {
    setActionMessage("Acknowledge the custom firmware and RF compliance warning first.", "error");
    els.advancedModemAcknowledge.focus();
    return;
  }
  if (!state.config?.gateway_password_configured) {
    setActionMessage("Save the gateway admin password before creating a recovery bundle.", "error");
    els.gatewayPassword.focus();
    return;
  }

  await runAction("Creating the G4AR Docker recovery bundle.", async () => {
    const manifest = await api("/api/g4ar/firmware/backup", {
      method: "POST",
      body: { reason: "ui_request" },
    });
    state.firmwareBackups = await api("/api/g4ar/firmware/backups");
    renderAdvancedModemControls();
    return `Recovery bundle saved: ${manifest.id}. Download the ZIP below.`;
  });
}

async function saveSettings() {
  const testsPerHour = Number.parseInt(els.testFrequency.value, 10);
  if (!Number.isFinite(testsPerHour) || testsPerHour < 1 || testsPerHour > 720) {
    setActionMessage("Checks per hour must be between 1 and 720.", "error");
    els.testFrequency.focus();
    return;
  }

  if (!els.dryRunToggle.checked && !state.config?.gateway_password_configured) {
    activateView("settings", { refreshMap: false });
    setActionMessage("Save the gateway admin password before turning Dry Run off.", "error");
    els.gatewayPassword.focus();
    return;
  }

  await runAction("Saving settings.", async () => {
    state.config = await api("/api/settings", {
      method: "POST",
      body: {
        dry_run: els.dryRunToggle.checked,
        tests_per_hour: testsPerHour,
      },
    });
    renderAll();
    return "Settings saved.";
  });
}

async function saveSpeedTestSchedule() {
  const cadence = els.speedTestCadence.value;
  const profile = els.speedTestProfile.value;
  const retentionDays = Number(els.speedTestRetention.value);
  const timezoneOffsetMinutes = -new Date().getTimezoneOffset();
  const usage = speedTestUsageEstimate(cadence, profile);
  const currentRetentionDays = speedTestRetentionDays();
  const confirmations = [];

  if (
    cadence !== "disabled" &&
    (usage.runsPerDay >= 144 || usage.thirtyDayBytes >= 100_000_000_000)
  ) {
    confirmations.push(
      `This schedule can run ${usage.runsPerDay.toFixed(0)} tests per day and transfer up to ${formatDataSize(usage.thirtyDayBytes)} in 30 days.`
    );
  }
  if (retentionDays < currentRetentionDays) {
    confirmations.push(
      `Reducing history from ${formatRetention(currentRetentionDays)} to ${formatRetention(retentionDays)} permanently removes older speed-test records.`
    );
  }
  if (confirmations.length) {
    const confirmed = window.confirm(
      `${confirmations.join("\n\n")}\n\nSave these settings?`
    );
    if (!confirmed) {
      return;
    }
  }

  await runAction("Saving speed test schedule.", async () => {
    state.speedTestStatus = await api("/api/speedtest/settings", {
      method: "POST",
      body: {
        cadence,
        profile,
        timezone_offset_minutes: timezoneOffsetMinutes,
        retention_days: retentionDays,
      },
    });
    if (state.speedTestRange === "all" || state.speedTestDays > retentionDays) {
      state.speedTestRange = "all";
      state.speedTestDays = retentionDays;
      state.speedTestHistory = await api(
        `/api/speedtest/history?days=${state.speedTestDays}`
      );
    }
    await applySpeedTestDefaultRange();
    state.config = await api("/api/config");
    renderAll();
    return cadence === "disabled"
      ? "Speed settings saved; automatic tests are off."
      : "Speed test settings saved.";
  });
}

async function runSpeedTestNow() {
  const savedProfile = state.speedTestStatus?.profile?.key || "gentle";
  const estimatedBytes =
    Number(state.speedTestStatus?.profile?.estimated_bytes) ||
    SPEED_TEST_PROFILE_BYTES[savedProfile] ||
    SPEED_TEST_PROFILE_BYTES.gentle;
  const confirmed = window.confirm(
    `Run one ${savedProfile} speed test now? It can transfer up to ${formatDataSize(estimatedBytes)} and may briefly use part of the internet connection.`
  );
  if (!confirmed) {
    return;
  }

  state.speedTestBusy = true;
  await runAction("Running sequential download and upload samples.", async () => {
    const result = await api("/api/speedtest/run", { method: "POST" });
    const [status, history] = await Promise.all([
      api("/api/speedtest/status"),
      api(`/api/speedtest/history?days=${state.speedTestDays}`),
    ]);
    state.speedTestStatus = status;
    state.speedTestHistory = history;
    renderAll();
    return `Speed test complete: ${formatSpeedResult(result.download_mbps)} down, ${formatSpeedResult(result.upload_mbps)} up.`;
  });
  state.speedTestBusy = false;
  renderSpeedTests();
  updateControlState();
}

async function requestReboot() {
  const force = els.forceReboot.checked;
  const confirmed = window.confirm(
    force
      ? "Force a gateway reboot request now?"
      : "Request a gateway reboot if limits allow it?"
  );
  if (!confirmed) {
    return;
  }

  await runAction("Requesting gateway reboot.", async () => {
    state.status = await api("/api/reboot", {
      method: "POST",
      body: { force },
    });
    await refreshGatewayAndEvents();
    renderAll();
    return state.status?.dry_run
      ? "Dry run recorded. No live reboot was sent."
      : "Gateway reboot request sent.";
  });
}

async function startSweep() {
  if (state.seriesRunning) {
    return;
  }

  const count = clamp(Number.parseInt(els.seriesCount.value, 10) || 1, 1, 30);
  const intervalSeconds = clamp(Number.parseFloat(els.seriesInterval.value) || 0, 0, 300);
  els.seriesCount.value = String(count);
  els.seriesInterval.value = String(intervalSeconds);
  replaceChildren(els.seriesTableBody);

  state.seriesRunning = true;
  state.seriesAbort = false;
  updateControlState();
  setActionMessage("Diagnostic sweep running.", "");

  try {
    for (let index = 1; index <= count; index += 1) {
      if (state.seriesAbort) {
        break;
      }
      state.status = await api("/api/check", { method: "POST" });
      addSeriesRow(index, state.status);
      await refreshGatewayAndEvents();
      renderAll();
      if (index < count && intervalSeconds > 0 && !state.seriesAbort) {
        await sleep(intervalSeconds * 1000);
      }
    }
    setActionMessage(state.seriesAbort ? "Diagnostic sweep stopped." : "Diagnostic sweep complete.", "success");
  } catch (error) {
    setActionMessage(error.message, "error");
  } finally {
    state.seriesRunning = false;
    state.seriesAbort = false;
    updateControlState();
  }
}

function stopSweep() {
  state.seriesAbort = true;
  updateControlState();
}

function addSeriesRow(index, status) {
  const row = document.createElement("tr");
  row.append(
    tableCell(String(index)),
    tableCell(formatDate(status.last_check_at) || formatTime(new Date())),
    tableCell(statusBadge(status.internet_online)),
    tableCell(`${status.successful_probes || 0} / ${status.total_probes || 0}`),
    tableCell(phaseText(status.phase) || "Unknown")
  );
  els.seriesTableBody.prepend(row);
}

async function refreshGatewayAndEvents() {
  const [overviewResult, wifiResult, clientsResult, mapResult, eventsResult] = await Promise.allSettled([
    api("/api/gateway/overview"),
    api("/api/gateway/wifi"),
    api("/api/gateway/clients"),
    api("/api/gateway/map?include_nearby=false"),
    api("/api/events?limit=10"),
  ]);
  if (overviewResult.status === "fulfilled") {
    state.overview = overviewResult.value;
  }
  if (wifiResult.status === "fulfilled") {
    state.wifi = wifiResult.value;
  }
  if (clientsResult.status === "fulfilled") {
    state.clients = clientsResult.value;
  }
  if (mapResult.status === "fulfilled") {
    state.mapData = mapResult.value;
  }
  if (eventsResult.status === "fulfilled") {
    state.events = eventsResult.value;
  }
  try {
    state.telemetryHistory = await api(
      `/api/gateway/telemetry/history?hours=${state.telemetryHours}`
    );
  } catch {
    // A diagnostic sweep can continue even if chart history is temporarily unavailable.
  }
}

async function runAction(workingMessage, action) {
  state.actionBusy = true;
  updateControlState();
  setActionMessage(workingMessage, "");
  hideError();
  try {
    const message = await action();
    setActionMessage(message, "success");
  } catch (error) {
    setActionMessage(error.message, "error");
  } finally {
    state.actionBusy = false;
    updateControlState();
  }
}

function updateControlState() {
  const busy =
    state.refreshing ||
    state.actionBusy ||
    state.mapBusy ||
    state.gatewayLoginBusy ||
    state.snapshotBusy ||
    state.speedTestBusy ||
    state.seriesRunning;
  const hasPassword = Boolean(els.gatewayPassword.value);
  const configured = Boolean(state.config?.gateway_password_configured);
  const openCellIdConfigured = Boolean(state.config?.map?.opencellid_configured);
  const advancedEnabled = Boolean(els.advancedLabEnabled?.checked);
  const g4arLabEnabled = advancedEnabled;
  const g4arLabSaved = isG4ARLabMode(state.config?.advanced_modem?.mode);
  const g4arBackupReady =
    g4arLabSaved &&
    els.advancedModemAcknowledge.checked &&
    configured;
  const firmwareConsentPhrase =
    state.config?.advanced_modem?.g4ar_unlock_lab?.consent_phrase ||
    state.config?.advanced_modem?.g4ar_firmware_lab?.consent_phrase ||
    "I OWN THIS G4AR - BACKUP VERIFIED - OVERRIDE RISK ACCEPTED";
  const hasFirmwareGateInputs =
    els.firmwareBackupSha256.value.trim().length === 64 &&
    els.firmwareSha256.value.trim().length === 64 &&
    els.firmwareConsentPhrase.value.trim() === firmwareConsentPhrase &&
    els.firmwareBackupVerified.checked &&
    els.firmwareRecoveryVerified.checked &&
    els.firmwareUnderstandsRisk.checked;

  els.refreshButton.disabled = state.refreshing;
  els.refreshClientsButton.disabled = busy || !configured;
  els.lookupClientsButton.disabled = busy || !configured;
  els.checkButton.disabled = busy;
  els.gatewayButton.disabled = busy || (!configured && !hasPassword);
  els.saveGatewayButton.disabled = busy || !hasPassword;
  els.forgetGatewayButton.disabled = busy || !configured;
  els.saveWifiButton.disabled = busy || !configured || !els.wifiSsid.value.trim();
  els.saveSettingsButton.disabled = busy;
  els.speedTestRunButton.disabled = busy || Boolean(state.speedTestStatus?.running);
  els.speedTestSaveButton.disabled = busy;
  els.speedTestCadence.disabled = busy;
  els.speedTestProfile.disabled = busy;
  els.speedTestRetention.disabled = busy;
  els.downloadSnapshotButton.disabled = busy;
  els.saveAdvancedModemButton.disabled =
    busy || (advancedEnabled && !els.advancedModemAcknowledge.checked);
  els.rebootButton.disabled = busy || (!configured && !state.config?.dry_run);
  els.gatewayPassword.disabled = busy;
  els.rememberPassword.disabled = busy;
  els.wifiSsid.disabled = busy || !configured;
  els.wifiRadioToggle.disabled = busy || !configured;
  els.dryRunToggle.disabled = busy;
  els.testFrequency.disabled = busy;
  els.advancedLabEnabled.disabled = busy;
  els.advancedModemAcknowledge.disabled = busy || !advancedEnabled;
  els.advancedUploadProfile.disabled = busy || !advancedEnabled;
  els.advancedRadioProfile.disabled = busy || !g4arLabEnabled;
  els.skipStockBackupReminder.disabled = busy || !g4arLabEnabled;
  els.firmwareBackupButton.disabled = busy || !g4arBackupReady;
  els.firmwareBackupSha256.disabled = busy || !g4arLabEnabled;
  els.firmwareSha256.disabled = busy || !g4arLabEnabled;
  els.firmwareConsentPhrase.disabled = busy || !g4arLabEnabled;
  els.firmwareBackupVerified.disabled = busy || !g4arLabEnabled;
  els.firmwareRecoveryVerified.disabled = busy || !g4arLabEnabled;
  els.firmwareUnderstandsRisk.disabled = busy || !g4arLabEnabled;
  els.firmwareFlashButton.disabled = busy || !g4arLabEnabled || !hasFirmwareGateInputs;
  [
    els.rootOwnsHardware,
    els.rootNotLeased,
    els.rootSpareUnit,
    els.rootRevisionRecorded,
    els.rootUartVoltageVerified,
    els.rootBootLogCaptured,
    els.rootFullBackupVerified,
    els.rootOfflineRecoveryVerified,
    els.rootAcceptsBrickRisk,
    els.rootConsentPhrase,
  ].forEach((input) => {
    input.disabled = busy || !g4arLabEnabled;
  });
  els.rootAssessButton.disabled =
    busy || !g4arLabEnabled || !els.advancedModemAcknowledge.checked;
  els.forceReboot.disabled = busy;
  els.seriesStartButton.disabled = busy;
  els.seriesStopButton.disabled = !state.seriesRunning;
  els.seriesCount.disabled = busy;
  els.seriesInterval.disabled = busy;
  els.mapRefreshButton.disabled = busy;
  els.useBrowserLocationButton.disabled = busy;
  els.useGatewayLocationButton.disabled = busy;
  els.saveMapCenterButton.disabled =
    busy ||
    !els.mapLatitude.value.trim() ||
    !els.mapLongitude.value.trim() ||
    !els.mapRadius.value.trim();
  els.saveOpenCellIdButton.disabled = busy || !els.openCellIdKey.value.trim();
  els.clearOpenCellIdButton.disabled = busy || !openCellIdConfigured;
  els.mapLatitude.disabled = busy;
  els.mapLongitude.disabled = busy;
  els.mapRadius.disabled = busy;
  els.openCellIdKey.disabled = busy;
  els.darkModeToggle.disabled = false;
}

function selectTab(name) {
  document.querySelectorAll(".tab").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.tab === name);
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => {
    panel.classList.toggle("is-active", panel.id === `tab-${name}`);
  });
}

function setActionMessage(message, tone) {
  setText(els.actionMessage, message || "");
  els.actionMessage.className = "message";
  if (tone) {
    els.actionMessage.classList.add(`message--${tone}`);
  }
}

function showError(message) {
  setText(els.errorBanner, message);
  els.errorBanner.classList.remove("alert--hidden");
}

function hideError() {
  els.errorBanner.classList.add("alert--hidden");
  setText(els.errorBanner, "");
}

function setTag(element, label, tone = "muted") {
  setText(element, label);
  element.className = `tag tag--${tone}`;
}

function setTone(element, tone) {
  element.classList.remove("tone-good", "tone-bad", "tone-warn", "tone-info", "tone-muted");
  element.classList.add(`tone-${tone || "muted"}`);
}

function toneFromBoolean(value) {
  if (value === true) {
    return "good";
  }
  if (value === false) {
    return "bad";
  }
  return "muted";
}

function toneFromQuality(value) {
  const quality = String(value || "").toLowerCase();
  if (quality === "excellent" || quality === "good") {
    return "good";
  }
  if (quality === "fair") {
    return "warn";
  }
  if (quality === "weak" || quality === "poor") {
    return "bad";
  }
  return "muted";
}

function toneFromPhase(phase) {
  if (!phase) {
    return "muted";
  }
  if (phase === "online") {
    return "good";
  }
  if (phase.includes("grace") || phase.includes("cooldown") || phase.includes("dry_run")) {
    return "warn";
  }
  if (phase.includes("error") || phase.includes("failed") || phase.includes("outage")) {
    return "bad";
  }
  return "info";
}

function booleanLabel(value, truthy, falsy, unknown = "Unknown") {
  if (value === true) {
    return truthy;
  }
  if (value === false) {
    return falsy;
  }
  return unknown;
}

function phaseText(value) {
  return value ? humanize(value) : "";
}

function statusBadge(success, statusCode) {
  const span = document.createElement("span");
  span.className = `inline-status inline-status--${toneFromBoolean(success)}`;
  if (success === true) {
    span.textContent = statusCode ? `OK ${statusCode}` : "OK";
  } else if (success === false) {
    span.textContent = statusCode ? `Failed ${statusCode}` : "Failed";
  } else {
    span.textContent = "Unknown";
  }
  return span;
}

function tableCell(value) {
  const cell = document.createElement("td");
  if (value instanceof Node) {
    cell.append(value);
  } else {
    cell.textContent = formatValue(value);
  }
  return cell;
}

function addEmptyTableRow(body, columns, message) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = columns;
  cell.append(emptyNode(message));
  row.append(cell);
  body.append(row);
}

function emptyNode(message) {
  const node = document.createElement("p");
  node.className = "empty-state";
  node.textContent = message;
  return node;
}

function replaceChildren(element) {
  while (element.firstChild) {
    element.removeChild(element.firstChild);
  }
}

function setText(element, value) {
  element.textContent = value;
}

function compactJoin(values, separator = " ") {
  return values.filter((value) => hasValue(value)).join(separator);
}

function hasValue(value) {
  if (value === null || value === undefined) {
    return false;
  }
  if (typeof value === "string") {
    return Boolean(value.trim());
  }
  return true;
}

function numericScore(value) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim()) {
    const number = Number.parseFloat(value.replace("%", ""));
    return Number.isFinite(number) ? number : NaN;
  }
  return NaN;
}

function formatValue(value) {
  if (value === null || value === undefined) {
    return "Unknown";
  }
  if (typeof value === "boolean") {
    return value ? "Yes" : "No";
  }
  return String(value);
}

function formatDate(value) {
  if (!value) {
    return "";
  }
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "";
  }
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatTime(value) {
  const date = value instanceof Date ? value : new Date(value);
  return date.toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

function formatLatency(value) {
  if (!Number.isFinite(value)) {
    return "Unknown";
  }
  if (value < 1000) {
    return `${Math.round(value)} ms`;
  }
  return `${(value / 1000).toFixed(2)} s`;
}

function formatNetworkSpeed(value) {
  const speed = Number(value);
  if (!Number.isFinite(speed) || speed <= 0) {
    return "Unknown";
  }
  if (speed >= 1000) {
    const gbps = speed / 1000;
    return `${Number.isInteger(gbps) ? gbps.toFixed(0) : gbps.toFixed(1)} Gbps`;
  }
  return `${Math.round(speed)} Mbps`;
}

function formatSpeedResult(value) {
  const speed = Number(value);
  return Number.isFinite(speed) ? `${speed.toFixed(speed >= 100 ? 0 : 1)} Mbps` : "--";
}

function formatMillisecondResult(value) {
  const milliseconds = Number(value);
  return Number.isFinite(milliseconds) ? `${milliseconds.toFixed(milliseconds >= 100 ? 0 : 1)} ms` : "--";
}

function formatDataSize(value) {
  const bytes = Math.max(0, Number(value) || 0);
  if (bytes >= 1_000_000_000_000) {
    return `${(bytes / 1_000_000_000_000).toFixed(2)} TB`;
  }
  if (bytes >= 1_000_000_000) {
    return `${(bytes / 1_000_000_000).toFixed(2)} GB`;
  }
  return `${(bytes / 1_000_000).toFixed(bytes >= 100_000_000 ? 0 : 1)} MB`;
}

function formatDistance(value) {
  if (!Number.isFinite(value)) {
    return "Unknown";
  }
  if (value < 1) {
    return `${Math.round(value * 1000)} m`;
  }
  return `${value.toFixed(value >= 10 ? 1 : 2)} km`;
}

function formatSignal(value) {
  if (!Number.isFinite(value)) {
    return "Unknown";
  }
  return `${Math.round(value)} dBm`;
}

function cleanUrl(url) {
  try {
    const parsed = new URL(url);
    return parsed.host;
  } catch {
    return url || "Probe";
  }
}

function humanize(value) {
  return String(value || "")
    .replace(/[_-]+/g, " ")
    .replace(/([a-z0-9])([A-Z])/g, "$1 $2")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function sleep(ms) {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms);
  });
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}
