const REFRESH_MS = 2000;
const DEV_API_KEY = "fl_dev_local";
const BASE_URL = window.location.origin;

const STARTER_CODE = `# pip install faultline-sdk
import faultline

run = faultline.start(
    "first-run",
    project="my-project",
    api_key="${DEV_API_KEY}",
    base_url="${BASE_URL}",
)

step = run.restore_latest(model=model, optimizer=optimizer)

for step in range(step, 10):
    run.log(loss=1.0 / (step + 1))
    if step % 5 == 0:
        run.save(model=model, optimizer=optimizer, step=step)

run.register_launch_command(["python", "train.py"])
run.complete()`;

const healthBadge = document.getElementById("health-badge");
const refreshBtn = document.getElementById("refresh-btn");
const autoRefreshCheckbox = document.getElementById("auto-refresh");
const runsTableBody = document.querySelector("#runs-table tbody");
const eventsTableBody = document.querySelector("#events-table tbody");
const checkpointsTableBody = document.querySelector("#checkpoints-table tbody");
const checkpointSummary = document.getElementById("checkpoint-summary");
const chartPanel = document.getElementById("chart-panel");
const chartTitle = document.getElementById("chart-title");
const metricSelect = document.getElementById("metric-select");
const metricsChartCanvas = document.getElementById("metrics-chart");
const recoveryPanel = document.getElementById("recovery-panel");
const recoveryBadge = document.getElementById("recovery-badge");
const recoveryLatestStep = document.getElementById("recovery-latest-step");
const recoveryCheckpointStep = document.getElementById("recovery-checkpoint-step");
const recoveryLostSteps = document.getElementById("recovery-lost-steps");
const recoveryCheckpointHealth = document.getElementById("recovery-checkpoint-health");
const recoveryCheckpointAge = document.getElementById("recovery-checkpoint-age");
const recoveryRestoreStatus = document.getElementById("recovery-restore-status");
const recoveryRecommendation = document.getElementById("recovery-recommendation");
const recoveryResumeSnippet = document.getElementById("recovery-resume-snippet");
const recoverySlurmSnippet = document.getElementById("recovery-slurm-snippet");
const copyResumeBtn = document.getElementById("copy-resume-btn");
const copySlurmBtn = document.getElementById("copy-slurm-btn");
const resumeRunBtn = document.getElementById("resume-run-btn");
const resumeStatusHint = document.getElementById("resume-status-hint");
const recoveryLaunchConfig = document.getElementById("recovery-launch-config");
const recoveryLastResume = document.getElementById("recovery-last-resume");
const recoveryTimeline = document.getElementById("recovery-timeline");
const errorBanner = document.getElementById("error-banner");
const lastUpdatedEl = document.getElementById("last-updated");
const usageList = document.getElementById("usage-list");
const apiKeyPrefixEl = document.getElementById("api-key-prefix");
const starterCodeBlock = document.getElementById("starter-code-block");
const copyKeyBtn = document.getElementById("copy-key-btn");
const copyCodeBtn = document.getElementById("copy-code-btn");

const DEFAULT_METRICS = [
  "loss",
  "learning_rate",
  "step_time_ms",
  "samples_per_sec",
  "cpu_percent",
  "memory_percent",
];

let selectedRunId = null;
let selectedMetric = "loss";
let cachedRuns = [];
let cachedMetricPoints = [];
let lastMetricsFingerprint = "";
let lastCheckpointsFingerprint = "";
let lastRecoveryFingerprint = "";
let cachedMetricKeysSignature = "";
let cachedRecovery = null;
let metricsChart = null;
let refreshTimer = null;

starterCodeBlock.textContent = STARTER_CODE;

function authHeaders() {
  return {
    Authorization: `Bearer ${DEV_API_KEY}`,
    Accept: "application/json",
  };
}

function formatValue(value) {
  if (value === null || value === undefined) {
    return "—";
  }
  return String(value);
}

function formatBytes(bytes) {
  if (bytes === null || bytes === undefined) {
    return "—";
  }
  const n = Number(bytes);
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

function formatAge(ms) {
  if (ms === null || ms === undefined) {
    return "—";
  }
  const seconds = Number(ms) / 1000;
  if (seconds < 60) return `${seconds.toFixed(0)}s`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

function recoveryFingerprint(recovery) {
  if (!recovery) return "";
  const last = recovery.last_resume;
  return [
    recovery.status,
    recovery.display_status,
    recovery.latest_step,
    recovery.latest_checkpoint_step,
    recovery.estimated_lost_steps,
    recovery.checkpoint_health,
    recovery.recovery_badge,
    recovery.can_resume,
    last?.launched_at_ms,
    last?.pid,
    last?.slurm_job_id,
  ].join(":");
}

const RESUME_EVENT_TYPES = new Set([
  "faultline.run.resume_requested",
  "faultline.run.resume_started",
  "faultline.run.resume_failed",
]);

async function postResume(runId) {
  const response = await fetch(
    `/v1/runs/${encodeURIComponent(runId)}/resume`,
    { method: "POST", headers: authHeaders() }
  );
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `HTTP ${response.status}`);
  }
  return response.json();
}

function recommendationText(recovery) {
  const map = {
    resume_from_checkpoint:
      "This run can resume from the latest checkpoint. Copy the snippet below into your training script.",
    no_checkpoint:
      "No checkpoint found. Re-start training from scratch or upload a checkpoint before the next crash.",
    run_completed: "Run completed successfully. No resume needed.",
  };
  return map[recovery.recommendation] || recovery.recommendation;
}

function renderRecoveryPanel(recovery) {
  if (!recovery || !selectedRunId) {
    recoveryPanel.classList.add("hidden");
    return;
  }
  recoveryPanel.classList.remove("hidden");
  cachedRecovery = recovery;

  const badge = recovery.recovery_badge || "unknown";
  recoveryBadge.textContent = badge.replace(/_/g, " ");
  recoveryBadge.className = `recovery-badge recovery-badge-${badge}`;

  recoveryLatestStep.textContent = formatValue(recovery.latest_step);
  recoveryCheckpointStep.textContent = recovery.has_checkpoint
    ? formatValue(recovery.latest_checkpoint_step)
    : "none";
  recoveryLostSteps.textContent = formatValue(recovery.estimated_lost_steps);
  recoveryCheckpointHealth.textContent = formatValue(recovery.checkpoint_health);
  recoveryCheckpointAge.textContent = formatAge(recovery.checkpoint_age_ms);
  recoveryRestoreStatus.textContent = formatValue(recovery.restore_status);
  recoveryRecommendation.textContent = recommendationText(recovery);
  recoveryResumeSnippet.textContent = recovery.resume_snippet || "";
  recoverySlurmSnippet.textContent = recovery.slurm_snippet || "";
  recoveryLaunchConfig.textContent = formatLaunchConfig(recovery.launch_config);
  recoveryLastResume.textContent = formatLastResume(recovery.last_resume);

  resumeRunBtn.disabled = !recovery.can_resume;
  resumeStatusHint.textContent = recovery.can_resume
    ? "Relaunch uses stored launch config (one click, no auto-retry loop)."
    : "Resume requires healthy checkpoint + launch config registration.";

  updateSelectedRunStatusCell(recovery);
}

function formatTimestamp(ms) {
  if (ms === null || ms === undefined) {
    return "—";
  }
  const date = new Date(Number(ms));
  if (Number.isNaN(date.getTime())) {
    return String(ms);
  }
  return date.toLocaleTimeString();
}

function statusClass(status) {
  const normalized = (status || "").toLowerCase().replace(/_/g, "-");
  return `status-pill status-${normalized}`;
}

function formatLaunchConfig(config) {
  if (!config) return "Not registered — call run.register_launch_command() or register_slurm_script()";
  if (config.launch_type === "local_command") {
    return `Type: local_command\nCommand: ${JSON.stringify(config.command)}\nWorking dir: ${config.working_dir || "(default)"}`;
  }
  return `Type: slurm_script\nScript: ${config.script_path}\nWorking dir: ${config.working_dir || "(default)"}`;
}

function formatLastResume(launch) {
  if (!launch) return "No resume attempts yet";
  const lines = [
    `Status: ${launch.status}`,
    `Launched: ${formatTimestamp(launch.launched_at_ms)}`,
  ];
  if (launch.pid != null) lines.push(`PID: ${launch.pid}`);
  if (launch.slurm_job_id) lines.push(`Slurm job: ${launch.slurm_job_id}`);
  if (launch.error_message) lines.push(`Error: ${launch.error_message}`);
  return lines.join("\n");
}

function renderRecoveryTimeline(events) {
  const resumeEvents = (events || []).filter((e) =>
    RESUME_EVENT_TYPES.has(e.event_type)
  );
  if (!resumeEvents.length) {
    recoveryTimeline.innerHTML = "<li class=\"hint\">No resume events yet</li>";
    return;
  }
  recoveryTimeline.innerHTML = resumeEvents
    .map(
      (e) =>
        `<li><span class="${levelClass(e.level)}">${formatValue(e.event_type)}</span> ${formatTimestamp(e.timestamp_ms)} — ${formatValue(e.message)}</li>`
    )
    .join("");
}

function updateSelectedRunStatusCell(recovery) {
  const row = runsTableBody.querySelector(".run-row-selected");
  if (!row || !recovery) return;
  const statusCell = row.children[2];
  const label = recovery.display_status || recovery.status;
  statusCell.innerHTML = `<span class="${statusClass(label)}">${formatValue(label)}</span>`;
}

function levelClass(level) {
  const normalized = (level || "").toLowerCase();
  if (normalized === "warn") return "level-pill level-warn";
  if (normalized === "error") return "level-pill level-error";
  return "level-pill level-info";
}

async function fetchJson(url) {
  const response = await fetch(url, { headers: authHeaders() });
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `HTTP ${response.status}`);
  }
  return response.json();
}

function renderAccount(me) {
  apiKeyPrefixEl.textContent = me.api_key.prefix;
  const u = me.usage;
  usageList.innerHTML = `
    <li>Runs created: <strong>${u.runs_created}</strong></li>
    <li>Metric points: <strong>${u.metric_points_ingested}</strong></li>
    <li>Events: <strong>${u.events_ingested}</strong></li>
    <li>Checkpoints: <strong>${u.checkpoints_created}</strong></li>
    <li>Checkpoint bytes: <strong>${formatBytes(u.checkpoint_bytes_uploaded)}</strong></li>
    <li>Last used: <strong>${formatTimestamp(u.last_used_at_ms)}</strong></li>
  `;
}

function metricsFingerprint(points) {
  if (!points.length) return "";
  const last = points[points.length - 1];
  return `${points.length}:${last.step}:${last.timestamp_ms}:${JSON.stringify(last.metrics ?? {})}`;
}

function checkpointsFingerprint(checkpoints) {
  if (!checkpoints.length) return "";
  return checkpoints.map((c) => `${c.checkpoint_id}:${c.step}`).join("|");
}

function metricKeysFromPoints(points) {
  const keys = new Set();
  for (const point of points) {
    if (!point.metrics) continue;
    for (const key of Object.keys(point.metrics)) {
      keys.add(key);
    }
  }
  const ordered = DEFAULT_METRICS.filter((key) => keys.has(key));
  for (const key of keys) {
    if (!ordered.includes(key)) ordered.push(key);
  }
  return ordered;
}

function updateMetricSelector(keys) {
  const signature = keys.join("\0");
  if (signature === cachedMetricKeysSignature) return;
  cachedMetricKeysSignature = signature;
  const previous = metricSelect.value;
  metricSelect.innerHTML = keys
    .map((key) => `<option value="${key}">${key}</option>`)
    .join("");
  if (keys.includes(previous)) {
    metricSelect.value = previous;
    selectedMetric = previous;
  } else if (keys.includes("loss")) {
    metricSelect.value = "loss";
    selectedMetric = "loss";
  } else if (keys.length > 0) {
    metricSelect.value = keys[0];
    selectedMetric = keys[0];
  }
}

function renderMetricsChart({ recreate = false } = {}) {
  const run = cachedRuns.find((entry) => entry.run_id === selectedRunId);
  const label = run ? `${run.project_name} / ${run.run_name}` : selectedRunId;
  const metric = selectedMetric || "loss";
  chartTitle.textContent = `${metric} — ${label}`;

  const steps = cachedMetricPoints.map((point) => point.step);
  const values = cachedMetricPoints.map((point) =>
    point.metrics && metric in point.metrics ? point.metrics[metric] : null
  );

  const canUpdateInPlace =
    !recreate && metricsChart && metricsChart.data.datasets[0]?.label === metric;

  if (canUpdateInPlace) {
    metricsChart.data.labels = steps;
    metricsChart.data.datasets[0].data = values;
    metricsChart.options.scales.y.title.text = metric;
    metricsChart.update("none");
    metricsChart.resize();
    return;
  }

  if (metricsChart) {
    metricsChart.destroy();
    metricsChart = null;
  }

  metricsChart = new Chart(metricsChartCanvas, {
    type: "line",
    data: {
      labels: steps,
      datasets: [
        {
          label: metric,
          data: values,
          borderColor: "#5b9cff",
          backgroundColor: "rgba(91, 156, 255, 0.12)",
          tension: 0.2,
          spanGaps: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      scales: {
        x: {
          title: { display: true, text: "step", color: "#8b9cb3" },
          ticks: { color: "#8b9cb3" },
          grid: { color: "#2a384d" },
        },
        y: {
          title: { display: true, text: metric, color: "#8b9cb3" },
          ticks: { color: "#8b9cb3" },
          grid: { color: "#2a384d" },
        },
      },
      plugins: { legend: { labels: { color: "#e8edf4" } } },
    },
  });
}

function renderRuns(runs) {
  cachedRuns = runs;
  if (!runs.length) {
    runsTableBody.innerHTML =
      '<tr class="empty-row"><td colspan="7">No cloud runs yet — run sdk/examples/cloud_pytorch_easy.py</td></tr>';
    chartPanel.classList.add("hidden");
    recoveryPanel.classList.add("hidden");
    selectedRunId = null;
    return;
  }

  if (selectedRunId && !runs.some((run) => run.run_id === selectedRunId)) {
    selectedRunId = runs[0].run_id;
  } else if (!selectedRunId) {
    selectedRunId = runs[0].run_id;
  }

  runsTableBody.innerHTML = runs
    .map(
      (run) => `
      <tr class="run-row${run.run_id === selectedRunId ? " run-row-selected" : ""}" data-run-id="${encodeURIComponent(run.run_id)}">
        <td title="${formatValue(run.run_id)}">${formatValue(run.run_name)}</td>
        <td>${formatValue(run.project_name)}</td>
        <td><span class="${statusClass(run.status)}">${formatValue(run.status)}</span></td>
        <td>${formatValue(run.latest_step)}</td>
        <td>${formatValue(run.latest_loss)}</td>
        <td>${formatValue(run.latest_checkpoint_step ?? 0)}</td>
        <td>${formatTimestamp(run.created_at_ms)}</td>
      </tr>`
    )
    .join("");

  runsTableBody.querySelectorAll(".run-row").forEach((row) => {
    row.addEventListener("click", () => {
      const nextRunId = decodeURIComponent(row.dataset.runId);
      if (nextRunId === selectedRunId) return;
      selectedRunId = nextRunId;
      lastMetricsFingerprint = "";
      lastCheckpointsFingerprint = "";
      lastRecoveryFingerprint = "";
      renderRuns(cachedRuns);
      loadSelectedRunDetails({ forceChart: true }).catch(showError);
    });
  });
}

function renderEvents(events) {
  if (!events.length) {
    eventsTableBody.innerHTML =
      '<tr class="empty-row"><td colspan="4">No events for this run</td></tr>';
    return;
  }
  eventsTableBody.innerHTML = events
    .map(
      (event) => `
      <tr>
        <td>${formatTimestamp(event.timestamp_ms)}</td>
        <td><span class="${levelClass(event.level)}">${formatValue(event.level)}</span></td>
        <td>${formatValue(event.event_type)}</td>
        <td class="message-cell" title="${formatValue(event.message)}">${formatValue(event.message)}</td>
      </tr>`
    )
    .join("");
}

function renderCheckpoints(checkpoints) {
  const run = cachedRuns.find((r) => r.run_id === selectedRunId);
  if (!selectedRunId) {
    checkpointSummary.textContent = "Select a run to view checkpoints.";
    checkpointsTableBody.innerHTML =
      '<tr class="empty-row"><td colspan="5">—</td></tr>';
    return;
  }
  checkpointSummary.textContent = `${checkpoints.length} checkpoint(s) · latest step ${formatValue(run?.latest_checkpoint_step ?? 0)}`;

  if (!checkpoints.length) {
    checkpointsTableBody.innerHTML =
      '<tr class="empty-row"><td colspan="5">No checkpoints uploaded</td></tr>';
    return;
  }

  checkpointsTableBody.innerHTML = checkpoints
    .map(
      (cp) => `
      <tr>
        <td>${cp.step}</td>
        <td>${formatBytes(cp.size_bytes)}</td>
        <td><span class="${statusClass(cp.status)}">${formatValue(cp.status)}</span></td>
        <td>${formatTimestamp(cp.created_at_ms)}</td>
        <td><button type="button" class="btn btn-small dl-btn" data-cp-id="${cp.checkpoint_id}">Download</button></td>
      </tr>`
    )
    .join("");

  checkpointsTableBody.querySelectorAll(".dl-btn").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const cpId = btn.dataset.cpId;
      downloadCheckpoint(
        `/v1/runs/${encodeURIComponent(selectedRunId)}/checkpoints/${encodeURIComponent(cpId)}/download`,
        `step_${btn.closest("tr").children[0].textContent}.pkl`
      ).catch(showError);
    });
  });
}

async function downloadCheckpoint(url, filename) {
  const response = await fetch(url, { headers: authHeaders() });
  if (!response.ok) {
    throw new Error(`Download failed: HTTP ${response.status}`);
  }
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

async function loadSelectedRunDetails({ forceChart = false } = {}) {
  if (!selectedRunId) {
    chartPanel.classList.add("hidden");
    recoveryPanel.classList.add("hidden");
    eventsTableBody.innerHTML =
      '<tr class="empty-row"><td colspan="4">Select a run</td></tr>';
    renderCheckpoints([]);
    return;
  }

  chartPanel.classList.remove("hidden");

  const [points, events, checkpoints, recovery] = await Promise.all([
    fetchJson(`/v1/runs/${encodeURIComponent(selectedRunId)}/metrics?limit=1000`),
    fetchJson(`/v1/runs/${encodeURIComponent(selectedRunId)}/events?limit=100`),
    fetchJson(`/v1/runs/${encodeURIComponent(selectedRunId)}/checkpoints`),
    fetchJson(
      `/v1/runs/${encodeURIComponent(selectedRunId)}/recovery?base_url=${encodeURIComponent(BASE_URL)}`
    ),
  ]);

  const fingerprint = metricsFingerprint(points);
  if (forceChart || fingerprint !== lastMetricsFingerprint) {
    lastMetricsFingerprint = fingerprint;
    cachedMetricPoints = points;
    updateMetricSelector(metricKeysFromPoints(points));
    renderMetricsChart({ recreate: forceChart });
  }

  const cpFp = checkpointsFingerprint(checkpoints);
  if (forceChart || cpFp !== lastCheckpointsFingerprint) {
    lastCheckpointsFingerprint = cpFp;
    renderCheckpoints(checkpoints);
  }

  renderEvents(events);
  renderRecoveryTimeline(events);

  const recFp = recoveryFingerprint(recovery);
  if (forceChart || recFp !== lastRecoveryFingerprint) {
    lastRecoveryFingerprint = recFp;
    renderRecoveryPanel(recovery);
  }
}

function showError(error) {
  errorBanner.textContent = `Refresh failed: ${error.message}`;
  errorBanner.classList.remove("hidden");
}

async function refreshAll() {
  errorBanner.classList.add("hidden");
  errorBanner.textContent = "";

  try {
    const [health, me, runs] = await Promise.all([
      fetchJson("/health"),
      fetchJson("/v1/me"),
      fetchJson("/v1/runs"),
    ]);
    healthBadge.textContent = health.status === "ok" ? "connected" : health.status;
    healthBadge.className = `badge ${health.status === "ok" ? "badge-ok" : "badge-bad"}`;
    renderAccount(me);
    renderRuns(runs);
    await loadSelectedRunDetails();
    lastUpdatedEl.textContent = `Last updated ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    healthBadge.textContent = "error";
    healthBadge.className = "badge badge-bad";
    showError(error);
  }
}

function resetAutoRefresh() {
  if (refreshTimer) {
    clearInterval(refreshTimer);
    refreshTimer = null;
  }
  if (autoRefreshCheckbox.checked) {
    refreshTimer = setInterval(refreshAll, REFRESH_MS);
  }
}

copyKeyBtn.addEventListener("click", () => {
  navigator.clipboard.writeText(DEV_API_KEY).catch(() => {});
});
copyCodeBtn.addEventListener("click", () => {
  navigator.clipboard.writeText(STARTER_CODE).catch(() => {});
});
copyResumeBtn.addEventListener("click", () => {
  if (cachedRecovery?.resume_snippet) {
    navigator.clipboard.writeText(cachedRecovery.resume_snippet).catch(() => {});
  }
});
copySlurmBtn.addEventListener("click", () => {
  if (cachedRecovery?.slurm_snippet) {
    navigator.clipboard.writeText(cachedRecovery.slurm_snippet).catch(() => {});
  }
});
resumeRunBtn.addEventListener("click", async () => {
  if (!selectedRunId) return;
  resumeRunBtn.disabled = true;
  resumeStatusHint.textContent = "Resuming…";
  try {
    const result = await postResume(selectedRunId);
    resumeStatusHint.textContent = `Started (pid=${result.pid ?? "—"}, slurm=${result.slurm_job_id ?? "—"})`;
    lastRecoveryFingerprint = "";
    lastCheckpointsFingerprint = "";
    await refreshAll();
  } catch (error) {
    showError(error);
    resumeStatusHint.textContent = "Resume failed";
    resumeRunBtn.disabled = false;
  }
});
refreshBtn.addEventListener("click", refreshAll);
autoRefreshCheckbox.addEventListener("change", resetAutoRefresh);
metricSelect.addEventListener("change", () => {
  selectedMetric = metricSelect.value;
  if (cachedMetricPoints.length > 0) {
    renderMetricsChart({ recreate: true });
  }
});

refreshAll();
resetAutoRefresh();
