import { cookies } from "next/headers";
import { NextRequest, NextResponse } from "next/server";

const SESSION_COOKIE = "faultline_session";

/** Server-only Faultline Cloud backend URL (Docker internal or local). */
export function backendConfig() {
  const url =
    process.env.FAULTLINE_API_URL?.replace(/\/$/, "") ??
    "http://127.0.0.1:8080";
  return { url };
}

/**
 * Read the browser session JWT from the incoming request or Next.js cookie store.
 */
export async function readSessionToken(
  request?: NextRequest
): Promise<string | undefined> {
  if (request) {
    const fromRequest = request.cookies.get(SESSION_COOKIE)?.value;
    if (fromRequest) return fromRequest;
  }
  try {
    const store = await cookies();
    return store.get(SESSION_COOKIE)?.value;
  } catch {
    return undefined;
  }
}

/**
 * Proxy a browser request to the FastAPI cloud API using the logged-in session.
 * Sends the session JWT as Authorization Bearer (reliable in Docker BFF → API).
 */
export async function proxyToBackend(
  path: string,
  init: RequestInit = {},
  request?: NextRequest
): Promise<NextResponse> {
  const { url } = backendConfig();
  const headers = new Headers(init.headers);

  const sessionToken = await readSessionToken(request);
  if (sessionToken) {
    headers.set("Authorization", `Bearer ${sessionToken}`);
  }

  if (!headers.has("Authorization")) {
    return NextResponse.json(
      { detail: "Not authenticated — log in at /login" },
      { status: 401 }
    );
  }

  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }

  const response = await fetch(`${url}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });

  const contentType =
    response.headers.get("content-type") ?? "application/octet-stream";
  const body = await response.arrayBuffer();

  const nextHeaders = new Headers();
  nextHeaders.set("Content-Type", contentType);
  const disposition = response.headers.get("content-disposition");
  if (disposition) {
    nextHeaders.set("Content-Disposition", disposition);
  }

  return new NextResponse(body, {
    status: response.status,
    statusText: response.statusText,
    headers: nextHeaders,
  });
}

/**
 * Public web origin for browser redirects and OAuth callbacks.
 * Normalizes 0.0.0.0 → localhost (Docker bind address is not valid in browsers).
 */
export function publicAppUrl(): string {
  const raw =
    process.env.NEXT_PUBLIC_APP_URL?.replace(/\/$/, "") ??
    "http://localhost:3000";
  try {
    const url = new URL(raw);
    if (url.hostname === "0.0.0.0") {
      url.hostname = "localhost";
    }
    return url.toString().replace(/\/$/, "");
  } catch {
    return "http://localhost:3000";
  }
}

/** Public API URL for recovery snippets (browser / training scripts). */
export function publicApiUrl(): string {
  return (
    process.env.NEXT_PUBLIC_FAULTLINE_API_URL?.replace(/\/$/, "") ??
    "http://127.0.0.1:8080"
  );
}

export function recoveryPath(runId: string): string {
  const base = encodeURIComponent(publicApiUrl());
  return `/v1/runs/${encodeURIComponent(runId)}/recovery?base_url=${base}`;
}
