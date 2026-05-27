import { NextRequest, NextResponse } from "next/server";
import { backendConfig, publicAppUrl } from "@/lib/server-api";

const OAUTH_STATE_COOKIE = "faultline_oauth_state";

type RouteContext = { params: Promise<{ provider: string }> };

export async function GET(
  request: NextRequest,
  context: RouteContext
): Promise<NextResponse> {
  const { provider } = await context.params;
  if (provider !== "google" && provider !== "github") {
    return NextResponse.json({ detail: "unsupported oauth provider" }, { status: 404 });
  }
  const appUrl = publicAppUrl();
  const redirectUri = `${appUrl}/api/auth/oauth/${provider}/callback`;
  const state = crypto.randomUUID();
  const { url } = backendConfig();
  const response = await fetch(
    `${url}/v1/auth/oauth/${provider}/start?redirect_uri=${encodeURIComponent(redirectUri)}&state=${encodeURIComponent(state)}`,
    { method: "GET", headers: { Accept: "application/json" }, cache: "no-store" }
  );
  const body = await response.text();
  if (!response.ok) {
    return new NextResponse(body, {
      status: response.status,
      headers: { "Content-Type": "application/json" },
    });
  }
  const parsed = JSON.parse(body) as { authorize_url: string };
  const redirect = NextResponse.redirect(parsed.authorize_url, 302);
  redirect.cookies.set(OAUTH_STATE_COOKIE, `${provider}:${state}`, {
    httpOnly: true,
    sameSite: "lax",
    path: "/",
    maxAge: 600,
    secure: process.env.NODE_ENV === "production",
  });
  return redirect;
}
