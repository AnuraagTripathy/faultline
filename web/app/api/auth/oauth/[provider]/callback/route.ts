import { NextRequest, NextResponse } from "next/server";
import { backendConfig, publicAppUrl } from "@/lib/server-api";

const SESSION_COOKIE = "faultline_session";
const OAUTH_STATE_COOKIE = "faultline_oauth_state";
const SESSION_MAX_AGE = 7 * 24 * 3600;

type RouteContext = { params: Promise<{ provider: string }> };

export async function GET(
  request: NextRequest,
  context: RouteContext
): Promise<NextResponse> {
  const { provider } = await context.params;
  const appOrigin = publicAppUrl();

  if (provider !== "google" && provider !== "github") {
    return NextResponse.redirect(new URL("/login?error=oauth_provider", appOrigin));
  }
  const url = new URL(request.url);
  const code = url.searchParams.get("code") ?? "";
  const state = url.searchParams.get("state") ?? "";
  const expected = request.cookies.get(OAUTH_STATE_COOKIE)?.value ?? "";
  if (!code || !state || expected !== `${provider}:${state}`) {
    return NextResponse.redirect(new URL("/login?error=oauth_state", appOrigin));
  }
  const redirectUri = `${appOrigin}/api/auth/oauth/${provider}/callback`;
  const { url: backend } = backendConfig();
  const response = await fetch(`${backend}/v1/auth/oauth/${provider}/callback`, {
    method: "POST",
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ code, redirect_uri: redirectUri }),
    cache: "no-store",
  });
  if (!response.ok) {
    const errBody = await response.text();
    let detail = "oauth exchange failed";
    try {
      const parsed = JSON.parse(errBody) as { detail?: string };
      if (parsed.detail) detail = parsed.detail;
    } catch {
      if (errBody) detail = errBody.slice(0, 200);
    }
    const loginUrl = new URL("/login", appOrigin);
    loginUrl.searchParams.set("error", "oauth_exchange");
    loginUrl.searchParams.set("detail", detail);
    return NextResponse.redirect(loginUrl);
  }
  const text = await response.text();
  const data = JSON.parse(text) as { access_token?: string };
  const next = NextResponse.redirect(new URL("/dashboard", appOrigin));
  next.cookies.set(OAUTH_STATE_COOKIE, "", {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 0,
  });
  if (data.access_token) {
    next.cookies.set(SESSION_COOKIE, data.access_token, {
      httpOnly: true,
      sameSite: "lax",
      path: "/",
      maxAge: SESSION_MAX_AGE,
      secure: process.env.NODE_ENV === "production",
    });
  }
  return next;
}
