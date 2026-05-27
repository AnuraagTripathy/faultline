import { NextRequest } from "next/server";
import { proxyToBackend } from "@/lib/server-api";

type RouteContext = { params: Promise<{ path?: string[] }> };

async function handle(request: NextRequest, path: string[] | undefined) {
  const segments = path ?? [];
  const backendPath = `/v1/${segments.join("/")}`;
  const url = new URL(request.url);
  const query = url.search;

  const headers = new Headers();
  headers.set("Accept", request.headers.get("accept") ?? "application/json");
  const contentType = request.headers.get("content-type");
  if (contentType) {
    headers.set("Content-Type", contentType);
  }

  const init: RequestInit = {
    method: request.method,
    headers,
    cache: "no-store",
  };

  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  return proxyToBackend(`${backendPath}${query}`, init, request);
}

export async function GET(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return handle(request, path);
}

export async function POST(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return handle(request, path);
}

export async function PUT(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return handle(request, path);
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return handle(request, path);
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return handle(request, path);
}
