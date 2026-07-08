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
  sourceTemplate: document.querySelector("#source-template"),
  destinationTemplate: document.querySelector("#destination-template"),
};

const APP_BUILD_ID = "bitrate-kbps-30s-v2";
const BITRATE_GRAPH_SECONDS = 30;
const BITRATE_GRAPH_POINTS = 30;

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
        <label class="switch"><input type="checkbox" class="dashboard-pipeline-enabled"><span></span></label>
        <button class="secondary edit-pipeline" type="button">Edit</button>
      </div>
    `;
    article.querySelector("strong").textContent = pipeline.name;
    article.querySelector(".pipeline-route").textContent = transcode
      ? `${sourceName} -> ${transcode.codec.toUpperCase()} ${transcode.video_bitrate_kbps} kbps -> ${destinationName}`
      : `${sourceName} -> direct copy -> ${destinationName}`;
    article.querySelector(".live-dot").classList.toggle("live", Boolean(pipelineStatus?.live));
    article.querySelector(".pipeline-bitrate").textContent = formatBitrate(pipelineStatus?.bitrateKbps || 0);
    renderBitrateGraph(article.querySelector(".pipeline-graph"), pipelineStatus?.bitrateHistory || []);
    article.querySelector(".dashboard-pipeline-enabled").checked = pipeline.enabled;
    article.querySelector(".dashboard-pipeline-enabled").addEventListener("change", (event) => {
      pipeline.enabled = event.target.checked;
      renderSettings();
      scheduleAutosave(0);
    });
    article.querySelector(".edit-pipeline").addEventListener("click", () => {
      fields.settingsDialog.showModal();
      activateTab("pipelines");
    });
    fields.pipelineList.append(article);
  }
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
  row.querySelector(".pipeline-mode").addEventListener("change", () => updateTranscodeVisibility(row));
  row.querySelector(".remove-pipeline").addEventListener("click", () => {
    row.remove();
    scheduleAutosave(0);
  });
  fields.pipelineSettings.append(row);
  updateTranscodeVisibility(row);
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
    fields.previewDetail.textContent = status.streamIncoming
      ? "Preview frames are updating."
      : status.sourcePublishing
        ? "Waiting for preview frames."
      : "Point OBS at the source URL when you are ready to stream.";
    if (status.source) {
      fields.sourceName.textContent = status.source.name;
      fields.sourceUrl.textContent = status.source.publicUrl;
      fields.sourceKey.value = status.source.stream;
      fields.sourceBitrate.textContent = formatBitrate(status.source.bitrateKbps || 0);
      renderBitrateGraph(fields.sourceBitrateGraph, status.source.bitrateHistory || []);
    }
    renderPipelineDashboard(status);
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
  fields.previewImage.hidden = !shouldShowPreview;
  fields.previewPlaceholder.hidden = shouldShowPreview;

  if (shouldShowPreview) {
    refreshPreviewImage();
    if (!previewTimer) {
      previewTimer = setInterval(refreshPreviewImage, 1000);
    }
    return;
  }

  fields.previewImage.removeAttribute("src");
  if (previewTimer) {
    clearInterval(previewTimer);
    previewTimer = null;
  }
}

function refreshPreviewImage() {
  fields.previewImage.src = `/preview/preview.jpg?v=${Date.now()}`;
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
  };
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

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => activateTab(tab.dataset.tab));
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

init();
