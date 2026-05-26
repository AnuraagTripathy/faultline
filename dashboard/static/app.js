const REFRESH_MS = 2000;

const overviewCardsEl = document.getElementById("overview-cards");
const metricsPanelEl = document.getElementById("metrics-panel");
const alertsTableBody = document.querySelector("#alerts-table tbody");
const runsTableBody = document.querySelector("#runs-table tbody");
const runChartPanel = document.getElementById("run-chart-panel");
const runChartTitle = document.getElementById("run-chart-title");
const runMetricsChartCanvas = document.getElementById("run-metrics-chart");
const runMetricSelect = document.getElementById("run-metric-select");

const DEFAULT_CHART_METRICS = [
  "loss",
  "learning_rate",
  "step_time_ms",
  "samples_per_sec",
  "cpu_percent",
  "memory_percent",
  "process_rss_mb",
  "gpu_memory_allocated_mb",
  "gpu_memory_reserved_mb",
];

let selectedRunId = null;
let selectedChartMetric = "loss";
let runMetricsChart = null;
let cachedRuns = [];
let cachedMetricPoints = [];
let lastMetricsFingerprint = "";
let cachedMetricKeysSignature = "";
const workersTableBody = document.querySelector("#workers-table tbody");
const eventsTableBody = document.querySelector("#events-table tbody");
const shardsTableBody = document.querySelector("#shards-table tbody");
const datasetSelect = document.getElementById("dataset-select");
const statusFilter = document.getElementById("status-filter");
const refreshBtn = document.getElementById("refresh-btn");
const autoRefreshCheckbox = document.getElementById("auto-refresh");
const healthBadge = document.getElementById("health-badge");
const errorBanner = document.getElementById("error-banner");
const lastUpdatedEl = document.getElementById("last-updated");

let refreshTimer = null;

function formatValue(value) {
  if (value === null || value === undefined) {
    return "—";
  }
  return String(value);
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
  const normalized = (status || "").toLowerCase();
  return `status-pill status-${normalized}`;
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(body || `HTTP ${response.status}`);
  }
  return response.json();
}

function renderOverview(overview) {
  const cards = [
    ["Datasets", overview.total_datasets],
    ["Shards", overview.total_shards],
    ["Pending", overview.pending_shards],
    ["Claimed", overview.claimed_shards],
    ["Completed", overview.completed_shards],
    ["Failed", overview.failed_shards],
    ["Checkpoints", overview.total_checkpoints],
    ["Workers", overview.workers_seen],
  ];

  overviewCardsEl.innerHTML = cards
    .map(
      ([label, value]) => `
      <div class="card">
        <div class="card-label">${label}</div>
        <div class="card-value">${formatValue(value)}</div>
      </div>`
    )
    .join("");

  const metrics = overview.async_metrics || {};
  metricsPanelEl.innerHTML = `
    <strong>Async metrics</strong>
    enqueued ${formatValue(metrics.total_enqueued)}
    · committed ${formatValue(metrics.total_committed)}
    · failed ${formatValue(metrics.total_failed)}
    · retries ${formatValue(metrics.total_retries)}
    · permanent ${formatValue(metrics.total_permanent_failures)}
    · dropped ${formatValue(metrics.total_dropped)}
    · bytes ${formatValue(metrics.total_bytes_written)}
    · avg write ${formatValue(metrics.average_write_time_ms)} ms
  `;
}

function renderRuns(runs) {
  cachedRuns = runs;
  if (!runs.length) {
    runsTableBody.innerHTML =
      '<tr class="empty-row"><td colspan="7">No runs yet</td></tr>';
    runChartPanel.classList.add("hidden");
    selectedRunId = null;
    lastMetricsFingerprint = "";
    cachedMetricPoints = [];
    if (runMetricsChart) {
      runMetricsChart.destroy();
      runMetricsChart = null;
    }
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
        <td>${formatTimestamp(run.latest_metric_at_ms || null)}</td>
        <td>${formatValue(run.latest_step)}</td>
        <td>${formatValue(run.latest_loss ?? run.loss)}</td>
        <td>${formatValue(run.latest_checkpoint_step)}</td>
      </tr>`
    )
    .join("");

  runsTableBody.querySelectorAll(".run-row").forEach((row) => {
    row.addEventListener("click", () => {
      selectedRunId = decodeURIComponent(row.dataset.runId);
      renderRuns(cachedRuns);
      loadRunMetricsChart(selectedRunId).catch((error) => {
        errorBanner.textContent = `Run metrics failed: ${error.message}`;
        errorBanner.classList.remove("hidden");
      });
    });
  });

  if (selectedRunId) {
    loadRunMetricsChart(selectedRunId).catch(() => {});
  }
}

function metricKeysFromPoints(points) {
  const keys = new Set();
  for (const point of points) {
    if (!point.metrics) {
      continue;
    }
    for (const key of Object.keys(point.metrics)) {
      if (key !== "client_timestamp_ms") {
        keys.add(key);
      }
    }
  }
  const ordered = DEFAULT_CHART_METRICS.filter((key) => keys.has(key));
  for (const key of keys) {
    if (!ordered.includes(key)) {
      ordered.push(key);
    }
  }
  return ordered;
}

function updateMetricSelector(keys) {
  const signature = keys.join("\0");
  if (signature === cachedMetricKeysSignature) {
    return;
  }
  cachedMetricKeysSignature = signature;

  const previous = runMetricSelect.value;
  runMetricSelect.innerHTML = keys
    .map((key) => `<option value="${key}">${key}</option>`)
    .join("");
  if (keys.includes(previous)) {
    runMetricSelect.value = previous;
    selectedChartMetric = previous;
  } else if (keys.includes("loss")) {
    runMetricSelect.value = "loss";
    selectedChartMetric = "loss";
  } else if (keys.length > 0) {
    runMetricSelect.value = keys[0];
    selectedChartMetric = keys[0];
  }
}

function renderRunMetricsChart() {
  const run = cachedRuns.find((entry) => entry.run_id === selectedRunId);
  const label = run
    ? `${run.project_name} / ${run.run_name}`
    : selectedRunId;
  const metric = selectedChartMetric || "loss";
  runChartTitle.textContent = `${metric} — ${label}`;

  const steps = cachedMetricPoints.map((point) => point.step);
  const values = cachedMetricPoints.map((point) =>
    point.metrics && metric in point.metrics ? point.metrics[metric] : null
  );

  if (runMetricsChart) {
    runMetricsChart.destroy();
  }

  runMetricsChart = new Chart(runMetricsChartCanvas, {
    type: "line",
    data: {
      labels: steps,
      datasets: [
        {
          label: metric,
          data: values,
          borderColor: "#3d8bfd",
          backgroundColor: "rgba(61, 139, 253, 0.15)",
          tension: 0.2,
          spanGaps: true,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: {
          title: { display: true, text: "step", color: "#8b9cb3" },
          ticks: { color: "#8b9cb3" },
          grid: { color: "#2d3a4f" },
        },
        y: {
          title: { display: true, text: metric, color: "#8b9cb3" },
          ticks: { color: "#8b9cb3" },
          grid: { color: "#2d3a4f" },
        },
      },
      plugins: {
        legend: { labels: { color: "#e7ecf3" } },
      },
    },
  });
}

async function loadRunMetricsChart(runId) {
  runChartPanel.classList.remove("hidden");
  cachedMetricPoints = await fetchJson(
    `/api/runs/${encodeURIComponent(runId)}/metrics?limit=1000`
  );
  updateMetricSelector(metricKeysFromPoints(cachedMetricPoints));
  renderRunMetricsChart();
}

function renderWorkers(workers) {
  if (!workers.length) {
    workersTableBody.innerHTML =
      '<tr class="empty-row"><td colspan="6">No workers seen yet</td></tr>';
    return;
  }

  workersTableBody.innerHTML = workers
    .map(
      (worker) => `
      <tr>
        <td>${formatValue(worker.worker_id)}</td>
        <td>${formatValue(worker.latest_checkpoint_step)}</td>
        <td>${formatValue(worker.latest_local_step)}</td>
        <td>${formatValue(worker.committed_checkpoints)}</td>
        <td>${formatValue(worker.claimed_shards)}</td>
        <td>${formatValue(worker.completed_shards)}</td>
      </tr>`
    )
    .join("");
}

function levelClass(level) {
  const normalized = (level || "").toLowerCase();
  if (normalized === "warn") return "level-pill level-warn";
  if (normalized === "error") return "level-pill level-error";
  return "level-pill level-info";
}

function renderEvents(events) {
  if (!events.length) {
    eventsTableBody.innerHTML =
      '<tr class="empty-row"><td colspan="8">No events yet</td></tr>';
    return;
  }

  eventsTableBody.innerHTML = events
    .map(
      (event) => `
      <tr>
        <td>${formatTimestamp(event.timestamp_ms)}</td>
        <td><span class="${levelClass(event.level)}">${formatValue(event.level)}</span></td>
        <td>${formatValue(event.event_type)}</td>
        <td>${formatValue(event.worker_id)}</td>
        <td>${formatValue(event.dataset_name)}</td>
        <td>${formatValue(event.shard_id)}</td>
        <td>${formatValue(event.step)}</td>
        <td class="message-cell" title="${formatValue(event.message)}">${formatValue(event.message)}</td>
      </tr>`
    )
    .join("");
}

function renderShards(shards) {
  if (!datasetSelect.value) {
    shardsTableBody.innerHTML =
      '<tr class="empty-row"><td colspan="6">Select a dataset</td></tr>';
    return;
  }

  if (!shards.length) {
    shardsTableBody.innerHTML =
      '<tr class="empty-row"><td colspan="6">No shards match this filter</td></tr>';
    return;
  }

  shardsTableBody.innerHTML = shards
    .map(
      (shard) => `
      <tr>
        <td>${formatValue(shard.shard_id)}</td>
        <td>${formatValue(shard.start)}</td>
        <td>${formatValue(shard.end)}</td>
        <td><span class="${statusClass(shard.status)}">${formatValue(shard.status)}</span></td>
        <td>${formatValue(shard.worker_id)}</td>
        <td>${formatTimestamp(shard.updated_at_ms)}</td>
      </tr>`
    )
    .join("");
}

function updateDatasetOptions(datasets, preserveSelection = true) {
  const previous = datasetSelect.value;
  datasetSelect.innerHTML = '<option value="">(select dataset)</option>';
  for (const dataset of datasets) {
    const option = document.createElement("option");
    option.value = dataset.name;
    option.textContent = `${dataset.name} (${dataset.total_shards} shards)`;
    datasetSelect.appendChild(option);
  }

  if (preserveSelection && previous && [...datasetSelect.options].some((o) => o.value === previous)) {
    datasetSelect.value = previous;
  } else if (datasets.length === 1) {
    datasetSelect.value = datasets[0].name;
  }
}

async function loadShards() {
  if (!datasetSelect.value) {
    renderShards([]);
    return [];
  }

  const params = new URLSearchParams();
  if (statusFilter.value) {
    params.set("status", statusFilter.value);
  }
  const query = params.toString();
  const url = `/api/shards/${encodeURIComponent(datasetSelect.value)}${query ? `?${query}` : ""}`;
  const shards = await fetchJson(url);
  renderShards(shards);
  return shards;
}

async function refreshAll() {
  errorBanner.classList.add("hidden");
  errorBanner.textContent = "";

  try {
    const health = await fetchJson("/health");
    healthBadge.textContent = health.status === "ok" ? "connected" : health.status;
    healthBadge.className = `badge ${health.status === "ok" ? "badge-ok" : "badge-bad"}`;

    const [overview, runs, workers, datasets, events, alerts] = await Promise.all([
      fetchJson("/api/overview"),
      fetchJson("/api/runs"),
      fetchJson("/api/workers"),
      fetchJson("/api/datasets"),
      fetchJson("/api/events?limit=100"),
      fetchJson("/api/alerts"),
    ]);

    renderOverview(overview, alerts.active_count);
    renderAlerts(alerts);
    renderRuns(runs);
    renderWorkers(workers);
    renderEvents(events);
    updateDatasetOptions(datasets);
    await Promise.all([loadShards(), refreshSelectedRunMetrics()]);

    lastUpdatedEl.textContent = `Last updated ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    healthBadge.textContent = "error";
    healthBadge.className = "badge badge-bad";
    errorBanner.textContent = `Refresh failed: ${error.message}`;
    errorBanner.classList.remove("hidden");
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

refreshBtn.addEventListener("click", refreshAll);
autoRefreshCheckbox.addEventListener("change", resetAutoRefresh);
datasetSelect.addEventListener("change", () => {
  loadShards().catch((error) => {
    errorBanner.textContent = `Shard load failed: ${error.message}`;
    errorBanner.classList.remove("hidden");
  });
});
statusFilter.addEventListener("change", () => {
  loadShards().catch((error) => {
    errorBanner.textContent = `Shard load failed: ${error.message}`;
    errorBanner.classList.remove("hidden");
  });
});

runMetricSelect.addEventListener("change", () => {
  selectedChartMetric = runMetricSelect.value;
  if (cachedMetricPoints.length > 0) {
    renderRunMetricsChart({ recreate: true });
  }
});

refreshAll();
resetAutoRefresh();
