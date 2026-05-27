"use client";

import { Logo } from "@/components/Logo";
import { cn } from "@/lib/cn";
import { fetchAuthMe, logout } from "@/lib/api";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

const links = [
  { href: "/dashboard", label: "Overview" },
  { href: "/runs", label: "Runs" },
  { href: "/alerts", label: "Alerts" },
  { href: "/quickstart", label: "Quickstart" },
  { href: "/account", label: "Account" },
];

const operatorLinks =
  process.env.NEXT_PUBLIC_FAULTLINE_OPERATOR_NAV === "true"
    ? [{ href: "/admin/infrastructure", label: "Infrastructure" }]
    : [];

export function Sidebar() {
  const pathname = usePathname();
  const router = useRouter();
  const [email, setEmail] = useState<string | null>(null);

  useEffect(() => {
    fetchAuthMe()
      .then((session) => setEmail(session.email))
      .catch(() => setEmail(null));
  }, []);

  async function handleLogout() {
    await logout();
    router.push("/login");
    router.refresh();
  }

  return (
    <aside className="flex w-52 shrink-0 flex-col border-r border-border bg-surface-elevated min-h-screen">
      <div className="px-5 py-5 border-b border-border">
        <Logo href="/dashboard" iconSize={34} textClassName="text-[18px]" />
      </div>
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {[...links, ...operatorLinks].map(({ href, label }) => {
          const active =
            pathname === href ||
            (href !== "/dashboard" && pathname.startsWith(href));
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "block rounded-lg px-3 py-2 text-sm no-underline hover:no-underline transition-colors",
                active
                  ? "text-accent font-medium bg-accent-soft"
                  : "text-muted hover:text-foreground hover:bg-surface-2"
              )}
            >
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="px-5 py-5 border-t border-border text-xs text-muted space-y-3">
        {email ? (
          <p className="truncate text-subtle" title={email}>
            {email}
          </p>
        ) : null}
        <button
          type="button"
          onClick={handleLogout}
          className="text-muted hover:text-foreground transition"
        >
          Log out
        </button>
      </div>
    </aside>
  );
}
