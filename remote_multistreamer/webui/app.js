const fields = {
  streamSummary: document.querySelector("#stream-summary"),
  previewFrame: document.querySelector("#preview-frame"),
  previewImage: document.querySelector("#preview-image"),
  previewPlaceholder: document.querySelector("#preview-placeholder"),
  previewTitle: document.querySelector("#preview-title"),
  previewDetail: document.querySelector("#preview-detail"),
  sourceName: document.querySelector("#source-name"),
  sourceUrl: document.querySelector("#source-url"),
  sourceKey: document.querySelector("#source-key"),
  toggleSourceKey: document.querySelector("#toggle-source-key"),
  copySourceKey: document.querySelector("#copy-source-key"),
  pipelineList: document.querySelector("#pipeline-list"),
  pipelineSettings: document.querySelector("#pipeline-settings"),
  sources: document.querySelector("#sources"),
  destinations: document.querySelector("#destinations"),
  ffmpegBinary: document.querySelector("#ffmpeg-binary"),
  ffmpegLogLevel: document.querySelector("#ffmpeg-log-level"),
  message: document.querySelector("#message"),
  statusDot: document.querySelector("#status-dot"),
  statusText: document.querySelector("#status-text"),
  startButton: document.querySelector("#start-button"),
  stopButton: document.querySelector("#stop-button"),
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

let config = null;
let messageTimer = null;
let previewTimer = null;
let autosaveTimer = null;
let autosaveInFlight = false;
let autosaveQueued = false;

async function request(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json();
  if (!response.ok) {
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

function renderConfig(nextConfig) {
  config = nextConfig;
  fields.ffmpegBinary.value = config.ffmpeg.binary;
  fields.ffmpegLogLevel.value = config.ffmpeg.log_level;
  renderPipelineDashboard();
  renderSettings();
  renderSourceSummary();
}

function renderSourceSummary() {
  const source = config.sources[0];
  if (!source) {
    fields.sourceName.textContent = "-";
    fields.sourceUrl.textContent = "-";
    fields.sourceKey.value = "";
    return;
  }
  const host = source.host === "0.0.0.0" ? "RELAY_PUBLIC_IP" : source.host;
  fields.sourceName.textContent = source.name;
  fields.sourceUrl.textContent = `rtmp://${host}:${source.port}/${source.app}`;
  fields.sourceKey.value = source.stream;
}

function renderPipelineDashboard() {
  fields.pipelineList.replaceChildren();
  if (!config.pipelines.length) {
    const empty = document.createElement("p");
    empty.className = "empty-state";
    empty.textContent = "No pipelines configured.";
    fields.pipelineList.append(empty);
    return;
  }
  for (const pipeline of config.pipelines) {
    const source = sourceById(pipeline.source_id || pipeline.source);
    const destination = destinationById(pipeline.destination_id || pipeline.destination);
    const sourceName = source?.name || pipeline.source_id || pipeline.source || "";
    const destinationName = destination?.name || pipeline.destination_id || pipeline.destination || "";
    const article = document.createElement("article");
    article.className = "pipeline-row";
    const transcode = pipeline.transcodes[0];
    article.innerHTML = `
      <div>
        <strong></strong>
        <span></span>
      </div>
      <div class="row-actions">
        <label class="switch"><input type="checkbox" class="dashboard-pipeline-enabled"><span></span></label>
        <button class="secondary edit-pipeline" type="button">Edit</button>
      </div>
    `;
    article.querySelector("strong").textContent = pipeline.name;
    article.querySelector("span").textContent = transcode
      ? `${sourceName} -> ${transcode.codec.toUpperCase()} ${transcode.video_bitrate_kbps} kbps -> ${destinationName}`
      : `${sourceName} -> direct copy -> ${destinationName}`;
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
      renderPipelineDashboard();
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
    fields.statusDot.classList.toggle("running", status.running);
    fields.previewFrame.classList.toggle("live", status.streamIncoming);
    fields.statusText.textContent = status.running ? `Running, PID ${status.pid}` : "Stopped";
    fields.streamSummary.textContent = status.running ? "Relay is active and waiting for OBS input." : "Relay is stopped.";
    updateControlButtons(status.running);
    updatePreview(status);
    fields.previewTitle.textContent = status.streamIncoming ? "Stream relay active" : "No stream detected";
    fields.previewDetail.textContent = status.streamIncoming
      ? "Waiting for preview frames."
      : "Start the relay, then point OBS at the source URL.";
    if (status.source) {
      fields.sourceName.textContent = status.source.name;
      fields.sourceUrl.textContent = status.source.publicUrl;
      fields.sourceKey.value = status.source.stream;
    }
    if (status.lastError) setMessage(status.lastError, true);
  } catch (error) {
    fields.statusText.textContent = "Unavailable";
    updateControlButtons(false);
    setMessage(error.message, true);
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
  try {
    renderConfig(await request("/api/config"));
    await refreshStatus();
    setMessage("Ready.");
  } catch (error) {
    setMessage(error.message, true);
  }
}

fields.settingsButton.addEventListener("click", () => fields.settingsDialog.showModal());
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

setInterval(refreshStatus, 5000);
init();
