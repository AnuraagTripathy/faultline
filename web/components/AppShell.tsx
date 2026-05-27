import { Sidebar } from "@/components/Sidebar";
import type { ReactNode } from "react";

export function AppShell({
  title,
  subtitle,
  children,
  actions,
}: {
  title: string;
  subtitle?: string;
  children: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <Sidebar />
      <div className="flex flex-1 flex-col min-w-0">
        <header className="flex flex-wrap items-start justify-between gap-4 border-b border-border bg-surface-elevated px-8 py-5">
          <div>
            <h1 className="text-lg font-semibold text-foreground tracking-tight">{title}</h1>
            {subtitle ? (
              <p className="text-sm text-muted mt-1">{subtitle}</p>
            ) : null}
          </div>
          {actions ? <div className="flex items-center gap-2">{actions}</div> : null}
        </header>
        <main className="flex-1 px-8 py-8 overflow-auto max-w-5xl">{children}</main>
      </div>
    </div>
  );
}
