import type {
  Checkpoint,
  CreateApiKeyResponse,
  Event,
  MeResponse,
  MetricPoint,
  RecoverySummary,
  ResumeResponse,
  Run,
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public body?: string
  ) {
    super(message);
    this.name = "ApiError";
  }
}

/** Browser calls Next.js BFF routes only — API key stays on the server. */
async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...options,
    credentials: "include",
    headers: {
      Accept: "application/json",
      ...(options.headers ?? {}),
    },
    cache: "no-store",
  });

  if (!response.ok) {
    const body = await response.text();
    throw new ApiError(
      `API ${options.method ?? "GET"} ${path} failed (${response.status})`,
      response.status,
      body
    );
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const text = await response.text();
  if (!text) {
    return undefined as T;
  }
  return JSON.parse(text) as T;
}

export async function fetchAuthMe(): Promise<import("./types").AuthSession> {
  return request("/api/auth/me");
}

export async function fetchConnectedAccounts(): Promise<import("./types").ConnectedAccount[]> {
  return request("/api/auth/providers");
}

export async function signup(email: string, password: string): Promise<import("./types").AuthSession> {
  return request("/api/auth/signup", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export async function login(email: string, password: string): Promise<import("./types").AuthSession> {
  return request("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export async function logout(): Promise<void> {
  await request("/api/auth/logout", { method: "POST" });
}

export async function fetchMe(): Promise<MeResponse> {
  return request("/api/me");
}

export async function fetchUsage(): Promise<MeResponse["usage"]> {
  return request("/api/usage");
}

export async function fetchRecoveryStats(): Promise<import("./types").RecoveryStats> {
  return request("/api/recovery/stats");
}

export async function fetchInfrastructure(): Promise<import("./types").InfrastructureStatus> {
  return request("/api/infrastructure");
}

export async function fetchAlertSettings(): Promise<import("./types").AlertSettings> {
  return request("/api/alert-settings");
}

export async function updateAlertSettings(
  settings: Partial<import("./types").AlertSettings>
): Promise<import("./types").AlertSettings> {
  return request("/api/alert-settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(settings),
  });
}

export async function fetchTasks(): Promise<import("./types").BackgroundTask[]> {
  return request("/api/tasks");
}

export async function evaluateAlerts(): Promise<{ status: string; task_id?: string }> {
  return request("/api/alerts/evaluate", { method: "POST" });
}

export async function fetchRuns(): Promise<Run[]> {
  return request("/api/runs");
}

export async function fetchRun(runId: string): Promise<Run> {
  return request(`/api/runs/${encodeURIComponent(runId)}`);
}

export async function fetchMetrics(
  runId: string,
  limit = 1000
): Promise<MetricPoint[]> {
  return request(
    `/api/runs/${encodeURIComponent(runId)}/metrics?limit=${limit}`
  );
}

export async function fetchEvents(
  runId: string,
  limit = 100
): Promise<Event[]> {
  return request(`/api/runs/${encodeURIComponent(runId)}/events?limit=${limit}`);
}

export async function fetchCheckpoints(runId: string): Promise<Checkpoint[]> {
  return request(`/api/runs/${encodeURIComponent(runId)}/checkpoints`);
}

export async function fetchRecovery(runId: string): Promise<RecoverySummary> {
  const base =
    typeof process !== "undefined" &&
    process.env.NEXT_PUBLIC_FAULTLINE_API_URL?.replace(/\/$/, "");
  const q = base ? `?base_url=${encodeURIComponent(base)}` : "";
  return request(`/api/runs/${encodeURIComponent(runId)}/recovery${q}`);
}

export async function resumeRun(runId: string): Promise<ResumeResponse> {
  return request(`/api/runs/${encodeURIComponent(runId)}/resume`, {
    method: "POST",
  });
}

export async function fetchApiKeys(): Promise<import("./types").ApiKeyListItem[]> {
  return request("/api/api-keys");
}

export async function createApiKey(
  label = "dev-key"
): Promise<CreateApiKeyResponse> {
  return request(`/api/api-keys?label=${encodeURIComponent(label)}`, {
    method: "POST",
  });
}

export async function downloadCheckpoint(
  runId: string,
  checkpointId: string,
  filename: string
): Promise<void> {
  const response = await fetch(
    `/api/runs/${encodeURIComponent(runId)}/checkpoints/${encodeURIComponent(checkpointId)}/download`,
    { credentials: "include" }
  );
  if (!response.ok) {
    throw new ApiError(`Download failed`, response.status);
  }
  const blob = await response.blob();
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = filename;
  link.click();
  URL.revokeObjectURL(link.href);
}

export const DEFAULT_METRICS = [
  "loss",
  "learning_rate",
  "accuracy",
  "step_time_ms",
];

export function metricKeysFromPoints(points: MetricPoint[]): string[] {
  const keys = new Set<string>();
  for (const point of points) {
    Object.keys(point.metrics ?? {}).forEach((k) => keys.add(k));
  }
  const ordered = DEFAULT_METRICS.filter((k) => keys.has(k));
  for (const k of keys) {
    if (!ordered.includes(k)) ordered.push(k);
  }
  return ordered;
}
