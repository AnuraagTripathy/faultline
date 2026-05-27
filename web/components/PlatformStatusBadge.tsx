"use client";

import type { InfrastructureStatus } from "@/lib/types";

export function PlatformStatusBadge({
  infra,
}: {
  infra: InfrastructureStatus | null;
}) {
  if (!infra) return null;

  const healthy =
    infra.database.status === "ok" &&
    infra.object_storage.status === "ok" &&
    infra.background_worker.status === "ok";

  return (
    <span
      className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium ${
        healthy
          ? "border-ok/40 bg-ok/10 text-ok"
          : "border-danger/40 bg-danger/10 text-danger"
      }`}
    >
      <span
        className={`h-1.5 w-1.5 rounded-full ${healthy ? "bg-ok" : "bg-danger"}`}
        aria-hidden
      />
      {healthy ? "Platform healthy" : "Platform degraded"}
    </span>
  );
}
