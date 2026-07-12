const fields = {
  loginScreen: document.querySelector("#login-screen"),
  loginForm: document.querySelector("#login-form"),
  loginUsername: document.querySelector("#login-username"),
  loginPassword: document.querySelector("#login-password"),
  loginButton: document.querySelector("#login-button"),
  loginMessage: document.querySelector("#login-message"),
  appShell: document.querySelector("#app-shell"),
  streamSummary: document.querySelector("#stream-summary"),
  previewFrame: document.querySelector("#preview-frame"),
  previewImage: document.querySelector("#preview-image"),
  previewPlaceholder: document.querySelector("#preview-placeholder"),
  previewTitle: document.querySelector("#preview-title"),
  previewDetail: document.querySelector("#preview-detail"),
  sourceName: document.querySelector("#source-name"),
  sourceUrl: document.querySelector("#source-url"),
  sourceKey: document.querySelector("#source-key"),
  sourceBitrate: document.querySelector("#source-bitrate"),
  sourceBitrateGraph: document.querySelector("#source-bitrate-graph"),
  toggleSourceKey: document.querySelector("#toggle-source-key"),
  copySourceKey: document.querySelector("#copy-source-key"),
  pipelineList: document.querySelector("#pipeline-list"),
  managerPreviewFrame: document.querySelector("#manager-preview-frame"),
  managerPreviewImage: document.querySelector("#manager-preview-image"),
  managerPreviewPlaceholder: document.querySelector("#manager-preview-placeholder"),
  managerPreviewTitle: document.querySelector("#manager-preview-title"),
  managerPreviewDetail: document.querySelector("#manager-preview-detail"),
  managerPreviewShell: document.querySelector("#manager-preview-shell"),
  managerPreviewToggle: document.querySelector("#manager-preview-toggle"),
  managerPipelineCards: document.querySelector("#manager-pipeline-cards"),
  managerPanels: document.querySelector("#manager-panels"),
  panelLayoutToggle: document.querySelector("#panel-layout-toggle"),
  pipelineSettings: document.querySelector("#pipeline-settings"),
  sources: document.querySelector("#sources"),
  destinations: document.querySelector("#destinations"),
  ffmpegBinary: document.querySelector("#ffmpeg-binary"),
  ffmpegLogLevel: document.querySelector("#ffmpeg-log-level"),
  authEnabled: document.querySelector("#auth-enabled"),
  authUsername: document.querySelector("#auth-username"),
  authPassword: document.querySelector("#auth-password"),
  authSummary: document.querySelector("#auth-summary"),
  authMessage: document.querySelector("#auth-message"),
  saveAuth: document.querySelector("#save-auth"),
  message: document.querySelector("#message"),
  statusDot: document.querySelector("#status-dot"),
  statusText: document.querySelector("#status-text"),
  startButton: document.querySelector("#start-button"),
  stopButton: document.querySelector("#stop-button"),
  logoutButton: document.querySelector("#logout-button"),
  settingsButton: document.querySelector("#settings-button"),
  settingsDialog: document.querySelector("#settings-dialog"),
  closeSettings: document.querySelector("#close-settings"),
  addPipelineMain: document.querySelector("#add-pipeline-main"),
  addPipeline: document.querySelector("#add-pipeline"),
  addSource: document.querySelector("#add-source"),
  addDestination: document.querySelector("#add-destination"),
  pipelineTemplate: document.querySelector("#pipeline-card-template"),
  panelTemplate: document.querySelector("#panel-row-template"),
  sourceTemplate: document.querySelector("#source-template"),
  destinationTemplate: document.querySelector("#destination-template"),
};

const APP_BUILD_ID = "stream-manager-v14";
const BITRATE_GRAPH_SECONDS = 30;
const BITRATE_GRAPH_POINTS = 30;
const MANAGER_PREVIEW_COLLAPSED_KEY = "fanout.managerPreviewCollapsed";
const PANEL_GRID_COLUMNS = 12;
const PANEL_GRID_MAX_ROWS = 6;

let config = null;
let messageTimer = null;
let previewTimer = null;
let autosaveTimer = null;
let autosaveInFlight = false;
let autosaveQueued = false;
let statusTimer = null;
let authEnabled = false;
let authSettings = null;
let lastStatus = null;
let managerPreviewCollapsed = localStorage.getItem(MANAGER_PREVIEW_COLLAPSED_KEY) === "true";
let panelEditMode = false;

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
    if (response.status === 401 && data.authRequired) {
      showLogin();
    }
    throw new Error(data.error || "Request failed");
  }
  return data;
}

function setMessage(text, isError = false, autoClearMs = 0) {
  if (messageTimer) {
    clearTimeout(messageTimer);
    messageTimer = null;
  }
  fields.message.textContent = text;
  fields.message.style.color = isError ? "var(--danger)" : "var(--muted)";
  if (autoClearMs > 0) {
    messageTimer = setTimeout(() => {
      fields.message.textContent = "";
      messageTimer = null;
    }, autoClearMs);
  }
}

function setLoginMessage(text, isError = false) {
  fields.loginMessage.textContent = text;
  fields.loginMessage.style.color = isError ? "var(--danger)" : "var(--muted)";
}

function setAuthMessage(text, isError = false) {
  fields.authMessage.textContent = text;
  fields.authMessage.style.color = isError ? "var(--danger)" : "var(--muted)";
}

function showLogin(username = "admin") {
  stopStatusRefresh();
  authEnabled = true;
  fields.appShell.hidden = true;
  fields.loginScreen.hidden = false;
  fields.logoutButton.hidden = true;
  fields.loginUsername.value = fields.loginUsername.value || username;
  fields.loginPassword.value = "";
  document.body.classList.remove("auth-checking");
  fields.loginUsername.focus();
}

function showApp() {
  fields.loginScreen.hidden = true;
  fields.appShell.hidden = false;
  fields.logoutButton.hidden = !authEnabled;
  document.body.classList.remove("auth-checking");
}

function renderAuthSettings(settings) {
  authSettings = settings;
  authEnabled = settings.enabled;
  fields.authEnabled.checked = settings.enabled;
  fields.authUsername.value = settings.username || "admin";
  fields.authPassword.value = "";
  fields.authSummary.textContent = settings.enabled
    ? `Login is on for ${settings.username}.`
    : "Login is off.";
  fields.authPassword.placeholder = settings.passwordSet ? "Leave blank to keep current password" : "";
  fields.logoutButton.hidden = !settings.enabled;
}

async function loadAuthSettings() {
  const settings = await request("/api/auth/settings");
  renderAuthSettings(settings);
  return settings;
}

async function saveAuthSettings() {
  const enabled = fields.authEnabled.checked;
  const username = fields.authUsername.value;
  const password = fields.authPassword.value;
  if (enabled && !password && !authSettings?.passwordSet) {
    setAuthMessage("Set a password before enabling login.", true);
    fields.authPassword.focus();
    return;
  }
  fields.saveAuth.disabled = true;
  setAuthMessage("Saving login settings...");
  try {
    const settings = await request("/api/auth/settings", {
      method: "PUT",
      body: JSON.stringify({ enabled, username, password }),
    });
    renderAuthSettings(settings);
    setAuthMessage(settings.enabled ? "Login saved." : "Login disabled.", false);
    setMessage(settings.enabled ? "Login protection is on." : "Login protection is off.", false, 2200);
  } catch (error) {
    setAuthMessage(error.message, true);
  } finally {
    fields.saveAuth.disabled = false;
  }
}

function renderConfig(nextConfig) {
  config = nextConfig;
  fields.ffmpegBinary.value = config.ffmpeg.binary;
  fields.ffmpegLogLevel.value = config.ffmpeg.log_level;
  renderPipelineDashboard(lastStatus);
  renderStreamManager(lastStatus);
  renderSettings();
  renderSourceSummary();
}

function renderSourceSummary() {
  const source = config.sources[0];
  if (!source) {
    fields.sourceName.textContent = "-";
    fields.sourceUrl.textContent = "-";
    fields.sourceKey.value = "";
    fields.sourceBitrate.textContent = "0 kbps";
    renderBitrateGraph(fields.sourceBitrateGraph, []);
    return;
  }
  const host = source.host === "0.0.0.0" ? "RELAY_PUBLIC_IP" : source.host;
  fields.sourceName.textContent = source.name;
  fields.sourceUrl.textContent = `rtmp://${host}:${source.port}/${source.app}`;
  fields.sourceKey.value = source.stream;
  fields.sourceBitrate.textContent = "0 kbps";
  renderBitrateGraph(fields.sourceBitrateGraph, []);
}

function renderPipelineDashboard(status = null) {
  fields.pipelineList.replaceChildren();
  if (!config.pipelines.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No pipelines configured.";
    fields.pipelineList.append(empty);
    return;
  }
  const pipelineStatuses = new Map((status?.pipelines || []).map((pipeline) => [pipeline.name, pipeline]));
  for (const pipeline of config.pipelines) {
    const pipelineStatus = pipelineStatuses.get(pipeline.name);
    const source = sourceById(pipeline.source_id || pipeline.source);
    const destination = destinationById(pipeline.destination_id || pipeline.destination);
    const sourceName = source?.name || pipeline.source_id || pipeline.source || "";
    const destinationName = destination?.name || pipeline.destination_id || pipeline.destination || "";
    const article = document.createElement("article");
    article.className = "pipeline-row";
    const transcode = pipeline.transcodes[0];
    article.innerHTML = `
      <div class="pipeline-main">
        <div class="pipeline-title-row">
          <span class="live-dot"></span>
          <strong></strong>
          <span class="pipeline-bitrate"></span>
        </div>
        <span class="pipeline-route"></span>
        <svg class="bitrate-graph pipeline-graph" viewBox="0 0 180 42" role="img" aria-label="Pipeline bitrate graph"></svg>
      </div>
      <div class="row-actions">
        <span class="mini-badge pipeline-enabled-badge"></span>
        <span class="mini-badge pipeline-live-badge"></span>
        <label class="switch"><input type="checkbox" class="dashboard-pipeline-enabled"><span></span></label>
        <button class="secondary edit-pipeline" type="button">Edit</button>
      </div>
    `;
    const isLive = Boolean(pipelineStatus?.live);
    article.querySelector("strong").textContent = pipeline.name;
    article.querySelector(".pipeline-route").textContent = transcode
      ? `${sourceName} -> ${transcode.codec.toUpperCase()} ${transcode.video_bitrate_kbps} kbps -> ${destinationName}`
      : `${sourceName} -> direct copy -> ${destinationName}`;
    article.querySelector(".live-dot").classList.toggle("live", Boolean(pipelineStatus?.live));
    article.querySelector(".pipeline-bitrate").textContent = formatBitrate(pipelineStatus?.bitrateKbps || 0);
    renderBitrateGraph(article.querySelector(".pipeline-graph"), pipelineStatus?.bitrateHistory || []);
    setBadge(article.querySelector(".pipeline-enabled-badge"), pipeline.enabled ? "Enabled" : "Paused", pipeline.enabled ? "ready" : "idle");
    setBadge(
      article.querySelector(".pipeline-live-badge"),
      isLive ? "Live" : status?.running && pipeline.enabled ? "Waiting" : "Offline",
      isLive ? "live" : status?.running && pipeline.enabled ? "ready" : "idle",
    );
    if (pipelineStatus?.mode) {
      article.querySelector(".pipeline-live-badge").title = pipelineStatus.mode;
    }
    article.querySelector(".dashboard-pipeline-enabled").checked = pipeline.enabled;
    article.querySelector(".dashboard-pipeline-enabled").addEventListener("change", (event) => {
      pipeline.enabled = event.target.checked;
      renderSettings();
      renderStreamManager(lastStatus);
      scheduleAutosave(0);
    });
    article.querySelector(".edit-pipeline").addEventListener("click", () => {
      fields.settingsDialog.showModal();
      activateTab("pipelines");
    });
    fields.pipelineList.append(article);
  }
}

function renderStreamManager(status = null) {
  renderManagerPipelineCards(status);
  renderManagerPanels();
}

function renderManagerPipelineCards(status = null) {
  fields.managerPipelineCards.replaceChildren();
  if (!config?.pipelines?.length) {
    const empty = document.createElement("span");
    empty.className = "manager-pipeline-chip manager-pipeline-chip-empty";
    empty.textContent = "No pipelines configured.";
    fields.managerPipelineCards.append(empty);
    return;
  }

  const pipelineStatuses = new Map((status?.pipelines || []).map((pipeline) => [pipeline.name, pipeline]));
  for (const pipeline of config.pipelines) {
    const pipelineStatus = pipelineStatuses.get(pipeline.name);
    const destination = destinationById(pipeline.destination_id || pipeline.destination);
    const chip = document.createElement("span");
    chip.className = "manager-pipeline-chip";
    chip.innerHTML = `
      <span class="live-dot"></span>
      <strong></strong>
      <span class="manager-chip-status"></span>
      <span class="manager-chip-enabled"></span>
    `;
    const isLive = Boolean(pipelineStatus?.live);
    const state = isLive ? "Live" : status?.running && pipeline.enabled ? "Waiting" : "Offline";
    chip.classList.toggle("live", isLive);
    chip.classList.toggle("paused", !pipeline.enabled);
    chip.title = destination?.name ? `${pipeline.name} to ${destination.name}` : pipeline.name;
    chip.querySelector("strong").textContent = pipeline.name;
    chip.querySelector(".manager-chip-status").textContent = state;
    chip.querySelector(".manager-chip-enabled").textContent = pipeline.enabled ? "Enabled" : "Paused";
    chip.querySelector(".live-dot").classList.toggle("live", isLive);
    fields.managerPipelineCards.append(chip);
  }
}

function renderManagerPanels() {
  fields.managerPanels.replaceChildren();
  fields.managerPanels.classList.toggle("editing", panelEditMode);
  if (!config?.pipelines?.length) {
    renderPanelEmptyState("No panels configured.");
    return;
  }

  const activePanels = config.pipelines
    .flatMap((pipeline, pipelineIndex) => (pipeline.panels || [])
      .map((panel, panelIndex) => ({
        ...panel,
        pipelineIndex,
        panelIndex,
        pipelineName: pipeline.name,
      }))
      .filter((panel) => panel.enabled))
    .sort((left, right) => (left.order ?? 0) - (right.order ?? 0));
  if (!activePanels.length) {
    renderPanelEmptyState("Enable panels in pipeline settings to show embeds here.");
    return;
  }

  for (const panel of activePanels) {
    const embedUrl = normalizePanelEmbedUrl(panel.url);
    const article = document.createElement("article");
    article.className = "manager-panel";
    article.dataset.pipelineIndex = String(panel.pipelineIndex);
    article.dataset.panelIndex = String(panel.panelIndex);
    article.draggable = false;
    setPanelGridSize(article, panel);
    article.innerHTML = `
      <header>
        <button class="manager-panel-grab" type="button" title="Move panel" aria-label="Move panel">⠿</button>
        <div>
          <h3></h3>
          <p></p>
        </div>
        <a target="_blank" rel="noopener noreferrer">Open</a>
      </header>
      <div class="manager-panel-body">
        <iframe loading="lazy" referrerpolicy="no-referrer-when-downgrade" allow="autoplay; fullscreen"></iframe>
      </div>
      <button class="manager-panel-resize" type="button" title="Resize panel" aria-label="Resize panel"></button>
    `;
    article.querySelector("h3").textContent = panel.title;
    article.querySelector("p").textContent = panel.pipelineName;
    article.querySelector("a").href = embedUrl;
    article.querySelector("iframe").src = embedUrl;
    article.querySelector("iframe").title = `${panel.pipelineName}: ${panel.title}`;
    bindManagerPanelEditor(article);
    fields.managerPanels.append(article);
  }
}

function setPanelGridSize(element, panel) {
  element.style.setProperty("--panel-columns", String(clampNumber(panel.columns ?? 6, 1, PANEL_GRID_COLUMNS)));
  element.style.setProperty("--panel-rows", String(clampNumber(panel.rows ?? 4, 1, PANEL_GRID_MAX_ROWS)));
}

function bindManagerPanelEditor(article) {
  bindGrabHandle(article);
  bindResizeHandles(article);
}

function bindGrabHandle(article) {
  const grab = article.querySelector(".manager-panel-grab");
  grab.addEventListener("pointerdown", (event) => startPanelMove(event, article));
}

function bindResizeHandles(article) {
  for (const handle of article.querySelectorAll(".manager-panel-resize")) {
    handle.addEventListener("pointerdown", (event) => {
      if (!panelEditMode) return;
      startPanelResize(event, article);
    });
  }
}

function updatePanelLayoutToggle() {
  fields.panelLayoutToggle.textContent = panelEditMode ? "▣" : "✎";
  fields.panelLayoutToggle.title = panelEditMode ? "Save panel layout" : "Edit panel layout";
  fields.panelLayoutToggle.setAttribute("aria-label", fields.panelLayoutToggle.title);
}

function setPanelLayoutEditing(editing) {
  panelEditMode = editing;
  fields.managerPanels.classList.toggle("editing", editing);
  fields.panelLayoutToggle.classList.toggle("dirty", false);
  updatePanelLayoutToggle();
  renderManagerPanels();
}

async function togglePanelLayoutEditing() {
  if (!panelEditMode) {
    setPanelLayoutEditing(true);
    return;
  }

  syncPanelSettingsFromConfig();
  await saveConfig({ render: false, showMessage: false });
  renderSettings();
  setPanelLayoutEditing(false);
  setMessage("Panel layout saved.", false, 1600);
}

function notePanelLayoutChanged() {
  if (panelEditMode) {
    fields.panelLayoutToggle.classList.add("dirty");
  }
}

function panelDragKey(article) {
  return `${article.dataset.pipelineIndex}:${article.dataset.panelIndex}`;
}

function startPanelMove(event, article) {
  if (!panelEditMode) return;
  event.preventDefault();
  const grab = event.currentTarget;
  grab.setPointerCapture(event.pointerId);
  article.classList.add("dragging");

  const onMove = (moveEvent) => {
    const targetPanel = panelElementAtPoint(moveEvent.clientX, moveEvent.clientY, article);
    if (!targetPanel) return;
    movePanelDuringPointer(panelDragKey(article), panelDragKey(targetPanel), moveEvent);
  };
  const onEnd = () => {
    grab.removeEventListener("pointermove", onMove);
    grab.removeEventListener("pointerup", onEnd);
    grab.removeEventListener("pointercancel", onEnd);
    article.classList.remove("dragging");
    syncPanelSettingsFromConfig();
    renderSettings();
  };

  grab.addEventListener("pointermove", onMove);
  grab.addEventListener("pointerup", onEnd, { once: true });
  grab.addEventListener("pointercancel", onEnd, { once: true });
}

function movePanelDuringPointer(sourceKey, targetKey, event) {
  if (!sourceKey || sourceKey === targetKey) return;
  const sourceElement = panelElementByKey(sourceKey);
  const targetElement = panelElementByKey(targetKey);
  if (!sourceElement || !targetElement) return;

  const activeRefs = activePanelRefs();
  const sourceIndex = activeRefs.findIndex((ref) => ref.key === sourceKey);
  const targetIndex = activeRefs.findIndex((ref) => ref.key === targetKey);
  if (sourceIndex < 0 || targetIndex < 0) return;

  const targetRect = targetElement.getBoundingClientRect();
  const insertAfter = event.clientY > targetRect.top + (targetRect.height / 2);
  if (insertAfter && targetElement.nextElementSibling === sourceElement) return;
  if (!insertAfter && sourceElement.nextElementSibling === targetElement) return;

  const [source] = activeRefs.splice(sourceIndex, 1);
  let insertIndex = targetIndex;
  if (insertAfter && sourceIndex > targetIndex) {
    insertIndex = targetIndex + 1;
  }
  if (insertAfter && sourceIndex < targetIndex) {
    insertIndex = targetIndex;
  }
  if (!insertAfter && sourceIndex < targetIndex) {
    insertIndex = targetIndex - 1;
  }
  activeRefs.splice(insertIndex, 0, source);
  activeRefs.forEach((ref, index) => {
    config.pipelines[ref.pipelineIndex].panels[ref.panelIndex].order = index;
  });

  if (insertAfter) {
    targetElement.after(sourceElement);
  } else {
    targetElement.before(sourceElement);
  }
  syncPanelSettingsFromConfig();
  notePanelLayoutChanged();
}

function panelElementAtPoint(x, y, sourceElement) {
  sourceElement.classList.add("drag-source-hit-test");
  const element = document.elementFromPoint(x, y);
  sourceElement.classList.remove("drag-source-hit-test");
  return element?.closest?.(".manager-panel") || null;
}

function panelElementByKey(key) {
  return [...fields.managerPanels.querySelectorAll(".manager-panel")]
    .find((panel) => panelDragKey(panel) === key);
}

function activePanelRefs() {
  return config.pipelines
    .flatMap((pipeline, pipelineIndex) => (pipeline.panels || [])
      .map((panel, panelIndex) => ({
        key: `${pipelineIndex}:${panelIndex}`,
        pipelineIndex,
        panelIndex,
        enabled: panel.enabled,
        order: panel.order ?? 0,
      }))
      .filter((panel) => panel.enabled))
    .sort((left, right) => left.order - right.order);
}

function startPanelResize(event, article) {
  event.preventDefault();
  event.stopPropagation();
  article.classList.add("resizing");
  const panel = panelFromArticle(article);
  const startX = event.clientX;
  const startY = event.clientY;
  const startColumns = clampNumber(panel.columns ?? 6, 1, PANEL_GRID_COLUMNS);
  const startRows = clampNumber(panel.rows ?? 4, 1, PANEL_GRID_MAX_ROWS);
  const columnWidth = fields.managerPanels.getBoundingClientRect().width / PANEL_GRID_COLUMNS;
  const rowHeight = Number.parseFloat(getComputedStyle(fields.managerPanels).gridAutoRows) || 210;

  const onMove = (moveEvent) => {
    const columnDelta = (moveEvent.clientX - startX) / columnWidth;
    const rowDelta = (moveEvent.clientY - startY) / rowHeight;
    const nextColumns = clampNumber(Math.round(startColumns + columnDelta), 1, PANEL_GRID_COLUMNS);
    const nextRows = clampNumber(Math.round(startRows + rowDelta), 1, PANEL_GRID_MAX_ROWS);
    panel.columns = nextColumns;
    panel.rows = nextRows;
    setPanelGridSize(article, panel);
    notePanelLayoutChanged();
  };
  const onEnd = () => {
    window.removeEventListener("pointermove", onMove);
    window.removeEventListener("pointerup", onEnd);
    article.classList.remove("resizing");
    syncPanelSettingsFromConfig();
    renderSettings();
  };
  window.addEventListener("pointermove", onMove);
  window.addEventListener("pointerup", onEnd, { once: true });
}

function panelFromArticle(article) {
  return config.pipelines[Number(article.dataset.pipelineIndex)].panels[Number(article.dataset.panelIndex)];
}

function clampNumber(value, min, max) {
  return Math.min(max, Math.max(min, Number(value) || min));
}

function syncPanelSettingsFromConfig() {
  [...fields.pipelineSettings.querySelectorAll(".pipeline-card")].forEach((pipelineRow, pipelineIndex) => {
    const pipeline = config.pipelines[pipelineIndex];
    if (!pipeline) return;
    [...pipelineRow.querySelectorAll(".panel-row")].forEach((panelRow, panelIndex) => {
      const panel = pipeline.panels?.[panelIndex];
      if (!panel) return;
      panelRow.dataset.columns = String(panel.columns ?? 6);
      panelRow.dataset.rows = String(panel.rows ?? 4);
      panelRow.dataset.order = String(panel.order ?? panelIndex);
    });
  });
}

function renderPanelEmptyState(text) {
  const empty = document.createElement("p");
  empty.className = "empty-state";
  empty.textContent = text;
  fields.managerPanels.append(empty);
}

function normalizePanelEmbedUrl(rawUrl) {
  const panelUrl = normalizePanelUrlScheme(rawUrl);
  try {
    const url = new URL(panelUrl, window.location.href);
    const host = url.hostname.toLowerCase();
    if (host === "twitch.tv" || host === "www.twitch.tv") {
      return normalizeTwitchChatUrl(url);
    }
    if (host === "youtube.com" || host === "www.youtube.com" || host === "youtu.be") {
      return normalizeYoutubeChatUrl(url);
    }
    return url.toString();
  } catch (_error) {
    return panelUrl;
  }
}

function normalizePanelUrlScheme(rawUrl) {
  const url = rawUrl.trim();
  if (!url || /^https?:\/\//i.test(url)) {
    return url;
  }
  return `https://${url}`;
}

function normalizeTwitchChatUrl(url) {
  const parts = url.pathname.split("/").filter(Boolean);
  let channel = "";
  if (parts[0] === "embed" && parts[2] === "chat") {
    channel = parts[1];
  } else if (parts[0] === "popout" && parts[2] === "chat") {
    channel = parts[1];
  } else if (parts[1] === "chat") {
    channel = parts[0];
  }
  if (!channel) {
    return url.toString();
  }

  url.hostname = "www.twitch.tv";
  url.pathname = `/embed/${channel}/chat`;
  url.searchParams.set("parent", window.location.hostname);
  url.searchParams.set("darkpopout", "1");
  return url.toString();
}

function normalizeYoutubeChatUrl(url) {
  const videoId = youtubeVideoId(url);
  if (!videoId) {
    return url.toString();
  }

  url.hostname = "www.youtube.com";
  url.pathname = "/live_chat";
  url.search = "";
  url.searchParams.set("v", videoId);
  url.searchParams.set("embed_domain", window.location.hostname);
  return url.toString();
}

function youtubeVideoId(url) {
  const parts = url.pathname.split("/").filter(Boolean);
  if (url.pathname === "/live_chat") {
    return url.searchParams.get("v") || "";
  }
  if (url.hostname.toLowerCase() === "youtu.be") {
    return parts[0] || "";
  }
  if (parts[0] === "live" || parts[0] === "embed" || parts[0] === "shorts") {
    return parts[1] || "";
  }
  if (url.pathname === "/watch") {
    return url.searchParams.get("v") || "";
  }
  return "";
}

function renderSettings() {
  fields.pipelineSettings.replaceChildren();
  fields.sources.replaceChildren();
  fields.destinations.replaceChildren();

  for (const pipeline of config.pipelines) addPipelineRow(pipeline);
  for (const source of config.sources) addSourceRow(source);
  for (const destination of config.destinations) addDestinationRow(destination);
}

function addPipelineRow(pipeline = defaultPipeline()) {
  const row = fields.pipelineTemplate.content.firstElementChild.cloneNode(true);
  fillSelect(
    row.querySelector(".pipeline-source"),
    config.sources.map((source) => ({ value: source.id, label: source.name })),
    pipeline.source_id || pipeline.source,
  );
  fillSelect(
    row.querySelector(".pipeline-destination"),
    config.destinations.map((destination) => ({ value: destination.id, label: destination.name })),
    pipeline.destination_id || pipeline.destination,
  );
  const transcode = pipeline.transcodes[0] || defaultTranscode();
  row.querySelector(".pipeline-enabled").checked = pipeline.enabled;
  row.querySelector(".pipeline-name").value = pipeline.name;
  row.querySelector(".pipeline-mode").value = pipeline.transcodes.length ? "transcode" : "copy";
  row.querySelector(".pipeline-codec").value = transcode.codec;
  row.querySelector(".pipeline-video-bitrate").value = transcode.video_bitrate_kbps;
  row.querySelector(".pipeline-audio-bitrate").value = transcode.audio_bitrate_kbps;
  row.querySelector(".pipeline-preset").value = transcode.preset;
  for (const panel of pipeline.panels || []) addPanelRow(row, panel);
  row.querySelector(".add-panel").addEventListener("click", () => {
    addPanelRow(row);
    scheduleAutosave(0);
  });
  row.querySelector(".pipeline-mode").addEventListener("change", () => updateTranscodeVisibility(row));
  row.querySelector(".remove-pipeline").addEventListener("click", () => {
    row.remove();
    scheduleAutosave(0);
  });
  fields.pipelineSettings.append(row);
  updateTranscodeVisibility(row);
}

function addPanelRow(pipelineRow, panel = defaultPanel()) {
  const row = fields.panelTemplate.content.firstElementChild.cloneNode(true);
  row.querySelector(".panel-enabled").checked = panel.enabled ?? true;
  row.querySelector(".panel-title").value = panel.title;
  row.querySelector(".panel-url").value = panel.url;
  row.dataset.columns = String(panel.columns ?? 6);
  row.dataset.rows = String(panel.rows ?? 4);
  row.dataset.order = String(panel.order ?? panelListOrder(pipelineRow));
  row.querySelector(".remove-panel").addEventListener("click", () => {
    row.remove();
    scheduleAutosave(0);
  });
  pipelineRow.querySelector(".panel-list").append(row);
}

function addSourceRow(source = defaultSource()) {
  const row = fields.sourceTemplate.content.firstElementChild.cloneNode(true);
  row.dataset.id = source.id || makeId("source");
  row.querySelector(".source-enabled").checked = source.enabled;
  row.querySelector(".source-name").value = source.name;
  row.querySelector(".source-host").value = source.host;
  row.querySelector(".source-port").value = source.port;
  row.querySelector(".source-app").value = source.app;
  row.querySelector(".source-stream").value = source.stream;
  row.querySelector(".toggle-source-stream").addEventListener("click", () => {
    toggleSecretInput(
      row.querySelector(".source-stream"),
      row.querySelector(".toggle-source-stream"),
    );
  });
  row.querySelector(".copy-source-stream").addEventListener("click", () => {
    copyText(row.querySelector(".source-stream").value);
  });
  row.querySelector(".rotate-source-stream").addEventListener("click", async () => {
    const sourceId = row.dataset.id;
    try {
      await saveConfig();
      const saved = await request("/api/source-key/rotate", {
        method: "POST",
        body: JSON.stringify({ source_id: sourceId }),
      });
      renderConfig(saved);
      setMessage("Source stream key rotated.", false, 2200);
    } catch (error) {
      setMessage(error.message, true);
    }
  });
  row.querySelector(".remove-source").addEventListener("click", () => {
    row.remove();
    scheduleAutosave(0);
  });
  fields.sources.append(row);
}

function addDestinationRow(destination = defaultDestination()) {
  const row = fields.destinationTemplate.content.firstElementChild.cloneNode(true);
  row.dataset.id = destination.id || makeId("destination");
  row.querySelector(".destination-enabled").checked = destination.enabled;
  row.querySelector(".destination-name").value = destination.name;
  row.querySelector(".destination-service").value = destination.service || "custom";
  row.querySelector(".destination-stream-key").value = destination.stream_key || "";
  row.querySelector(".destination-url").value = destination.url;
  row.querySelector(".destination-service").addEventListener("change", () => updateDestinationFields(row));
  row.querySelector(".remove-destination").addEventListener("click", () => {
    row.remove();
    scheduleAutosave(0);
  });
  fields.destinations.append(row);
  updateDestinationFields(row);
}

function collectConfig() {
  return {
    ffmpeg: {
      binary: fields.ffmpegBinary.value,
      log_level: fields.ffmpegLogLevel.value,
    },
    sources: [...fields.sources.querySelectorAll(".settings-card")].map((row) => ({
      id: row.dataset.id,
      enabled: row.querySelector(".source-enabled").checked,
      name: row.querySelector(".source-name").value,
      host: row.querySelector(".source-host").value,
      port: Number(row.querySelector(".source-port").value),
      app: row.querySelector(".source-app").value,
      stream: row.querySelector(".source-stream").value,
    })),
    destinations: [...fields.destinations.querySelectorAll(".settings-card")].map((row) => ({
      id: row.dataset.id,
      enabled: row.querySelector(".destination-enabled").checked,
      name: row.querySelector(".destination-name").value,
      service: row.querySelector(".destination-service").value,
      stream_key: row.querySelector(".destination-stream-key").value,
      url: row.querySelector(".destination-url").value,
    })),
    pipelines: [...fields.pipelineSettings.querySelectorAll(".pipeline-card")].map((row) => {
      const mode = row.querySelector(".pipeline-mode").value;
      return {
        enabled: row.querySelector(".pipeline-enabled").checked,
        name: row.querySelector(".pipeline-name").value,
        source_id: row.querySelector(".pipeline-source").value,
        destination_id: row.querySelector(".pipeline-destination").value,
        transcodes: mode === "copy" ? [] : [{
          codec: row.querySelector(".pipeline-codec").value,
          video_bitrate_kbps: Number(row.querySelector(".pipeline-video-bitrate").value),
          audio_bitrate_kbps: Number(row.querySelector(".pipeline-audio-bitrate").value),
          preset: row.querySelector(".pipeline-preset").value,
        }],
        panels: [...row.querySelectorAll(".panel-row")].map((panelRow) => ({
          enabled: panelRow.querySelector(".panel-enabled").checked,
          title: panelRow.querySelector(".panel-title").value,
          url: normalizePanelUrlScheme(panelRow.querySelector(".panel-url").value),
          columns: Number(panelRow.dataset.columns || 6),
          rows: Number(panelRow.dataset.rows || 4),
          order: Number(panelRow.dataset.order || 0),
        })),
      };
    }),
  };
}

async function saveConfig({ render = true, showMessage = true } = {}) {
  try {
    const saved = await request("/api/config", {
      method: "PUT",
      body: JSON.stringify(collectConfig()),
    });
    if (render) {
      renderConfig(saved);
    } else {
      config = saved;
      syncSettingsFromConfig();
      renderPipelineDashboard(lastStatus);
      renderStreamManager(lastStatus);
      renderSourceSummary();
    }
    if (showMessage) {
      setMessage("Configuration saved.", false, 1800);
    }
    return saved;
  } catch (error) {
    setMessage(error.message, true);
    throw error;
  }
}

function scheduleAutosave(delayMs = 500) {
  if (!config) return;
  if (autosaveTimer) {
    clearTimeout(autosaveTimer);
  }
  setMessage("Saving changes...");
  autosaveTimer = setTimeout(runAutosave, delayMs);
}

async function runAutosave() {
  autosaveTimer = null;
  if (autosaveInFlight) {
    autosaveQueued = true;
    return;
  }

  autosaveInFlight = true;
  try {
    await saveConfig({ render: false, showMessage: false });
    setMessage("Configuration saved.", false, 1800);
  } catch (_error) {
    return;
  } finally {
    autosaveInFlight = false;
  }

  if (autosaveQueued) {
    autosaveQueued = false;
    scheduleAutosave(0);
  }
}

async function flushAutosave() {
  if (autosaveTimer) {
    clearTimeout(autosaveTimer);
    autosaveTimer = null;
    await runAutosave();
  }
  while (autosaveInFlight) {
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
}

function syncSettingsFromConfig() {
  const sourcesById = new Map(config.sources.map((source) => [source.id, source]));
  for (const row of fields.sources.querySelectorAll(".settings-card")) {
    const source = sourcesById.get(row.dataset.id);
    if (!source) continue;
    const streamInput = row.querySelector(".source-stream");
    if (!streamInput.value && source.stream) {
      streamInput.value = source.stream;
    }
  }
}

async function refreshStatus() {
  try {
    const status = await request("/api/status");
    lastStatus = status;
    fields.statusDot.classList.toggle("running", status.state === "waiting");
    fields.statusDot.classList.toggle("live", status.state === "live");
    fields.previewFrame.classList.toggle("live", status.streamIncoming);
    fields.managerPreviewFrame.classList.toggle("live", status.streamIncoming);
    fields.statusText.textContent = status.state === "live" ? "Live" : status.ready ? "Ready" : "Needs config";
    fields.streamSummary.textContent = status.state === "live"
      ? "Source is connected. Enabled pipelines will receive data as frames arrive."
      : "RTMP ingest is armed and waiting for a source.";
    updateControlButtons(status.running);
    updatePreview(status);
    fields.previewTitle.textContent = status.streamIncoming
      ? "Stream relay active"
      : status.sourcePublishing
        ? "Source connected"
        : "No stream detected";
    fields.managerPreviewTitle.textContent = fields.previewTitle.textContent;
    fields.previewDetail.textContent = status.streamIncoming
      ? "Preview frames are updating."
      : status.sourcePublishing
        ? "Waiting for preview frames."
      : "Point OBS at the source URL when you are ready to stream.";
    fields.managerPreviewDetail.textContent = fields.previewDetail.textContent;
    if (status.source) {
      fields.sourceName.textContent = status.source.name;
      fields.sourceUrl.textContent = status.source.publicUrl;
      fields.sourceKey.value = status.source.stream;
      fields.sourceBitrate.textContent = formatBitrate(status.source.bitrateKbps || 0);
      renderBitrateGraph(fields.sourceBitrateGraph, status.source.bitrateHistory || []);
    }
    if (config) {
      renderPipelineDashboard(status);
      renderManagerPipelineCards(status);
    }
    if (status.lastError) setMessage(status.lastError, true);
  } catch (error) {
    fields.statusText.textContent = "Unavailable";
    updateControlButtons(false);
    setMessage(error.message, true);
  }
}

function startStatusRefresh() {
  if (!statusTimer) {
    statusTimer = setInterval(refreshStatus, 1000);
  }
}

function stopStatusRefresh() {
  if (statusTimer) {
    clearInterval(statusTimer);
    statusTimer = null;
  }
  if (previewTimer) {
    clearInterval(previewTimer);
    previewTimer = null;
  }
}

function updateControlButtons(running) {
  fields.startButton.disabled = running;
  fields.stopButton.disabled = !running;
}

function updatePreview(status) {
  const shouldShowPreview = Boolean(status.streamIncoming && status.previewUrl);
  const shouldShowDashboardPreview = shouldShowPreview && isPageActive("dashboard");
  const shouldShowManagerPreview = shouldShowPreview && isPageActive("stream-manager") && !managerPreviewCollapsed;
  fields.previewImage.hidden = !shouldShowDashboardPreview;
  fields.previewPlaceholder.hidden = shouldShowDashboardPreview;
  fields.managerPreviewImage.hidden = !shouldShowManagerPreview;
  fields.managerPreviewPlaceholder.hidden = shouldShowManagerPreview || managerPreviewCollapsed;

  if (shouldShowDashboardPreview || shouldShowManagerPreview) {
    refreshPreviewImage();
    if (!previewTimer) {
      previewTimer = setInterval(refreshPreviewImage, 1000);
    }
    return;
  }

  fields.previewImage.removeAttribute("src");
  fields.managerPreviewImage.removeAttribute("src");
  if (previewTimer) {
    clearInterval(previewTimer);
    previewTimer = null;
  }
}

function refreshPreviewImage() {
  const src = `/preview/preview.jpg?v=${Date.now()}`;
  if (isPageActive("dashboard")) {
    fields.previewImage.src = src;
  }
  if (isPageActive("stream-manager") && !managerPreviewCollapsed) {
    fields.managerPreviewImage.src = src;
  }
}

function setManagerPreviewCollapsed(collapsed) {
  managerPreviewCollapsed = collapsed;
  localStorage.setItem(MANAGER_PREVIEW_COLLAPSED_KEY, String(collapsed));
  fields.managerPreviewShell.classList.toggle("collapsed", collapsed);
  fields.managerPreviewFrame.hidden = collapsed;
  fields.managerPreviewToggle.textContent = collapsed ? "▾" : "▴";
  fields.managerPreviewToggle.title = collapsed ? "Show stream preview" : "Collapse stream preview";
  fields.managerPreviewToggle.setAttribute("aria-label", fields.managerPreviewToggle.title);
  if (collapsed) {
    fields.managerPreviewImage.hidden = true;
    fields.managerPreviewPlaceholder.hidden = true;
    fields.managerPreviewImage.removeAttribute("src");
  } else if (lastStatus) {
    updatePreview(lastStatus);
  }
}

function formatBitrate(kbps) {
  const value = Number(kbps) || 0;
  return `${Math.round(value)} kbps`;
}

function renderBitrateGraph(svg, history) {
  if (!svg) return;
  const width = 180;
  const height = 42;
  const padding = 3;
  const nowSeconds = Date.now() / 1000;
  const windowSeconds = BITRATE_GRAPH_SECONDS;
  const samples = normalizeBitrateSamples(history, nowSeconds);
  svg.replaceChildren();
  if (samples.length < 2) {
    const line = document.createElementNS("http://www.w3.org/2000/svg", "path");
    line.setAttribute("d", `M ${padding} ${height - padding} L ${width - padding} ${height - padding}`);
    line.setAttribute("class", "bitrate-line muted");
    svg.append(line);
    return;
  }

  const max = Math.max(...samples.map((sample) => sample.bitrateKbps || 0), 1);
  const points = samples.map((sample, index) => {
    const x = padding + (index / (samples.length - 1)) * (width - padding * 2);
    const y = height - padding - ((sample.bitrateKbps || 0) / max) * (height - padding * 2);
    return [x, y];
  });
  const linePath = points.map(([x, y], index) => `${index ? "L" : "M"} ${x.toFixed(1)} ${y.toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L ${width - padding} ${height - padding} L ${padding} ${height - padding} Z`;
  const area = document.createElementNS("http://www.w3.org/2000/svg", "path");
  area.setAttribute("d", areaPath);
  area.setAttribute("class", "bitrate-area");
  const line = document.createElementNS("http://www.w3.org/2000/svg", "path");
  line.setAttribute("d", linePath);
  line.setAttribute("class", "bitrate-line");
  svg.append(area, line);
}

function normalizeBitrateSamples(history, nowSeconds) {
  const oldestTime = nowSeconds - BITRATE_GRAPH_SECONDS;
  const sortedSamples = (history || [])
    .map((sample) => ({
      time: Number(sample.time) || 0,
      bitrateKbps: Number(sample.bitrateKbps) || 0,
    }))
    .filter((sample) => sample.time >= oldestTime && sample.time <= nowSeconds + 1)
    .sort((left, right) => left.time - right.time);

  const points = [];
  let sampleIndex = 0;
  let latestBitrate = 0;
  for (let index = 0; index < BITRATE_GRAPH_POINTS; index += 1) {
    const pointTime =
      oldestTime + (index / (BITRATE_GRAPH_POINTS - 1)) * BITRATE_GRAPH_SECONDS;
    while (
      sampleIndex < sortedSamples.length &&
      sortedSamples[sampleIndex].time <= pointTime
    ) {
      latestBitrate = sortedSamples[sampleIndex].bitrateKbps;
      sampleIndex += 1;
    }
    points.push({ time: pointTime, bitrateKbps: latestBitrate });
  }
  return points;
}

async function startRelay(successMessage = "Relay started.") {
  try {
    await flushAutosave();
    await saveConfig({ showMessage: false });
    await request("/api/relay/start", { method: "POST" });
    await refreshStatus();
    setMessage(successMessage);
  } catch (error) {
    setMessage(error.message, true);
  }
}

async function stopRelay(successMessage = "Relay stopped.") {
  try {
    await request("/api/relay/stop", { method: "POST" });
    await refreshStatus();
    setMessage(successMessage);
  } catch (error) {
    setMessage(error.message, true);
  }
}

function fillSelect(select, values, selected) {
  select.replaceChildren();
  for (const item of values) {
    const option = document.createElement("option");
    option.value = item.value;
    option.textContent = item.label;
    select.append(option);
  }
  select.value = selected || values[0]?.value || "";
}

function updateTranscodeVisibility(row) {
  const enabled = row.querySelector(".pipeline-mode").value === "transcode";
  for (const field of row.querySelectorAll(".transcode-field")) {
    field.hidden = !enabled;
  }
}

function updateDestinationFields(row) {
  const service = row.querySelector(".destination-service").value;
  const pathField = row.querySelector(".destination-url-field");
  row.querySelector(".destination-key-field").hidden = service !== "youtube" && service !== "twitch";
  pathField.hidden = service !== "custom" && service !== "file";
  pathField.childNodes[0].nodeValue = service === "file" ? "Recording path" : "RTMP URL";
}

async function copyText(text) {
  if (!text) return;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      fallbackCopyText(text);
    }
    setMessage("Copied.", false, 1800);
  } catch (_error) {
    try {
      fallbackCopyText(text);
      setMessage("Copied.", false, 1800);
    } catch (_fallbackError) {
      setMessage("Copy failed. Reveal and copy manually.", true, 3000);
    }
  }
}

function fallbackCopyText(text) {
  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.append(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  textarea.remove();
  if (!copied) {
    throw new Error("Copy command failed.");
  }
}

function toggleSecretInput(input, button) {
  const shouldReveal = input.getAttribute("type") === "password";
  input.setAttribute("type", shouldReveal ? "text" : "password");
  if (button) {
    button.textContent = shouldReveal ? "○" : "◉";
    button.title = shouldReveal ? "Hide stream key" : "Reveal stream key";
    button.setAttribute("aria-label", button.title);
  }
}

function activateTab(name) {
  for (const tab of document.querySelectorAll(".tab")) {
    tab.classList.toggle("active", tab.dataset.tab === name);
  }
  for (const panel of document.querySelectorAll(".tab-panel")) {
    panel.classList.toggle("active", panel.id === `tab-${name}`);
  }
}

function activatePage(name) {
  for (const tab of document.querySelectorAll(".view-tab")) {
    tab.classList.toggle("active", tab.dataset.page === name);
  }
  for (const page of document.querySelectorAll(".app-page")) {
    const active = page.id === `page-${name}`;
    page.classList.toggle("active", active);
    page.hidden = !active;
  }
  if (lastStatus) {
    updatePreview(lastStatus);
  }
}

function isPageActive(name) {
  return document.querySelector(`#page-${name}`)?.classList.contains("active");
}

function defaultTranscode() {
  return { codec: "h264", video_bitrate_kbps: 6000, audio_bitrate_kbps: 160, preset: "veryfast" };
}

function defaultPipeline() {
  return {
    name: "New Pipeline",
    enabled: false,
    source_id: config.sources[0]?.id || "",
    destination_id: config.destinations[0]?.id || "",
    transcodes: [],
    panels: [],
  };
}

function defaultPanel() {
  return { enabled: true, title: "Panel", url: "https://", columns: 6, rows: 4, order: nextPanelOrder() };
}

function nextPanelOrder() {
  const orders = config?.pipelines?.flatMap((pipeline) => (pipeline.panels || []).map((panel) => panel.order ?? 0)) || [];
  return orders.length ? Math.max(...orders) + 1 : 0;
}

function panelListOrder(pipelineRow) {
  return pipelineRow.querySelectorAll(".panel-row").length;
}

function defaultSource() {
  return { id: makeId("source"), name: "new-source", enabled: true, host: "0.0.0.0", port: 1935, app: "live", stream: "stream" };
}

function defaultDestination() {
  const existing = new Set(
    [...fields.destinations.querySelectorAll(".destination-name")].map((input) => input.value),
  );
  if (!existing.has("youtube")) {
    return { id: makeId("destination"), name: "youtube", enabled: true, service: "youtube", stream_key: "", url: "" };
  }
  if (!existing.has("twitch")) {
    return { id: makeId("destination"), name: "twitch", enabled: true, service: "twitch", stream_key: "", url: "" };
  }
  if (!existing.has("recordings")) {
    return { id: makeId("destination"), name: "recordings", enabled: true, service: "file", stream_key: "", url: "/config/recordings" };
  }
  return { id: makeId("destination"), name: "custom", enabled: false, service: "custom", stream_key: "", url: "rtmp://" };
}

function sourceById(id) {
  return config.sources.find((source) => source.id === id || source.name === id);
}

function destinationById(id) {
  return config.destinations.find((destination) => destination.id === id || destination.name === id);
}

function setBadge(element, text, state) {
  element.textContent = text;
  element.classList.toggle("live", state === "live");
  element.classList.toggle("ready", state === "ready");
}

function makeId(prefix) {
  if (globalThis.crypto?.randomUUID) {
    return `${prefix}-${globalThis.crypto.randomUUID().slice(0, 8)}`;
  }
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

async function init() {
  document.documentElement.dataset.appVersion = APP_BUILD_ID;
  try {
    const auth = await request("/api/auth/status");
    authEnabled = auth.enabled;
    if (auth.enabled && !auth.authenticated) {
      showLogin(auth.username || "admin");
      return;
    }
    showApp();
    await loadAuthSettings();
    renderConfig(await request("/api/config"));
    await refreshStatus();
    startStatusRefresh();
    setMessage("Ready.");
  } catch (error) {
    if (fields.appShell.hidden) {
      setLoginMessage(error.message, true);
    } else {
      setMessage(error.message, true);
    }
  }
}

fields.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  fields.loginButton.disabled = true;
  setLoginMessage("Signing in...");
  try {
    const auth = await request("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: fields.loginUsername.value,
        password: fields.loginPassword.value,
      }),
    });
    authEnabled = auth.enabled;
    setLoginMessage("");
    fields.loginPassword.value = "";
    showApp();
    await loadAuthSettings();
    renderConfig(await request("/api/config"));
    await refreshStatus();
    startStatusRefresh();
    setMessage("Signed in.", false, 1800);
  } catch (error) {
    setLoginMessage(error.message, true);
  } finally {
    fields.loginButton.disabled = false;
  }
});

fields.logoutButton.addEventListener("click", async () => {
  try {
    await request("/api/auth/logout", { method: "POST" });
  } catch (_error) {
    // The local session is cleared either way from the user's perspective.
  }
  showLogin(fields.loginUsername.value || "admin");
  setLoginMessage("Signed out.");
});
fields.saveAuth.addEventListener("click", () => saveAuthSettings());

fields.settingsButton.addEventListener("click", async () => {
  fields.settingsDialog.showModal();
  try {
    await loadAuthSettings();
  } catch (error) {
    setMessage(error.message, true);
  }
});
fields.closeSettings.addEventListener("click", () => fields.settingsDialog.close());
fields.addPipeline.addEventListener("click", () => {
  addPipelineRow();
  scheduleAutosave(0);
});
fields.addPipelineMain.addEventListener("click", () => {
  fields.settingsDialog.showModal();
  activateTab("pipelines");
  addPipelineRow();
  scheduleAutosave(0);
});
fields.addSource.addEventListener("click", () => {
  addSourceRow();
  scheduleAutosave(0);
});
fields.addDestination.addEventListener("click", () => {
  addDestinationRow();
  scheduleAutosave(0);
});
fields.startButton.addEventListener("click", () => startRelay("Relay started."));
fields.stopButton.addEventListener("click", () => stopRelay("Relay stopped."));
fields.toggleSourceKey.addEventListener("click", () => {
  toggleSecretInput(fields.sourceKey, fields.toggleSourceKey);
});
fields.copySourceKey.addEventListener("click", () => copyText(fields.sourceKey.value));
fields.managerPreviewToggle.addEventListener("click", () => setManagerPreviewCollapsed(!managerPreviewCollapsed));
fields.panelLayoutToggle.addEventListener("click", () => togglePanelLayoutEditing());

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => activateTab(tab.dataset.tab));
}

for (const tab of document.querySelectorAll(".view-tab")) {
  tab.addEventListener("click", () => activatePage(tab.dataset.page));
}

for (const element of [
  fields.pipelineSettings,
  fields.sources,
  fields.destinations,
  fields.ffmpegBinary,
  fields.ffmpegLogLevel,
]) {
  element.addEventListener("input", () => scheduleAutosave());
  element.addEventListener("change", () => scheduleAutosave());
}

setManagerPreviewCollapsed(managerPreviewCollapsed);
init();
