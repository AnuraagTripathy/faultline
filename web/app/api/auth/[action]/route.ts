import { NextRequest, NextResponse } from "next/server";
import { backendConfig, readSessionToken } from "@/lib/server-api";

const SESSION_COOKIE = "faultline_session";
const SESSION_MAX_AGE = 7 * 24 * 3600;

type RouteContext = { params: Promise<{ action: string }> };

async function backendFetch(
  path: string,
  init: RequestInit,
  request: NextRequest
) {
  const { url } = backendConfig();
  const headers = new Headers(init.headers);
  const sessionToken = await readSessionToken(request);
  if (sessionToken) {
    headers.set("Authorization", `Bearer ${sessionToken}`);
  }
  if (!headers.has("Accept")) {
    headers.set("Accept", "application/json");
  }
  return fetch(`${url}${path}`, { ...init, headers, cache: "no-store" });
}

export async function GET(
  request: NextRequest,
  context: RouteContext
): Promise<NextResponse> {
  const { action } = await context.params;
  if (action === "providers") {
    const response = await backendFetch(
      "/v1/auth/providers",
      { method: "GET" },
      request
    );
    const body = await response.text();
    return new NextResponse(body, {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  }
  if (action !== "me") {
    return NextResponse.json({ detail: "method not allowed" }, { status: 405 });
  }
  const sessionToken = await readSessionToken(request);
  if (!sessionToken) {
    return NextResponse.json({ detail: "Not authenticated" }, { status: 401 });
  }
  const response = await backendFetch(
    "/v1/auth/me",
    { method: "GET" },
    request
  );
  const body = await response.text();
  return new NextResponse(body, {
    status: response.status,
    headers: { "Content-Type": "application/json" },
  });
}

export async function POST(
  request: NextRequest,
  context: RouteContext
): Promise<NextResponse> {
  const { action } = await context.params;
  const payload = await request.text();

  if (action === "logout") {
    await backendFetch("/v1/auth/logout", { method: "POST" }, request);
    const cleared = NextResponse.json({ ok: true, message: "logged out" });
    cleared.cookies.set(SESSION_COOKIE, "", {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: 0,
    });
    return cleared;
  }

  if (action !== "login" && action !== "signup") {
    return NextResponse.json({ detail: "not found" }, { status: 404 });
  }

  const { url } = backendConfig();
  const response = await fetch(`${url}/v1/auth/${action}`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: payload,
    cache: "no-store",
  });
  const text = await response.text();
  if (!response.ok) {
    return new NextResponse(text, {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  const data = JSON.parse(text) as { access_token?: string };
  const next = NextResponse.json(data, { status: 200 });
  if (data.access_token) {
    next.cookies.set(SESSION_COOKIE, data.access_token, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: SESSION_MAX_AGE,
    });
  }
  return next;
}
