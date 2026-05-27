"use client";

import { Button } from "@/components/ui/button";
import { SiteNav } from "@/components/SiteNav";
import { login, ApiError } from "@/lib/api";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

const OAUTH_ERROR_MESSAGES: Record<string, string> = {
  oauth_exchange:
    "GitHub/Google sign-in failed during token exchange. Try again once, or use email/password.",
  oauth_state: "Sign-in session expired. Click the provider button again.",
  oauth_provider: "Unknown sign-in provider.",
};

export function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const code = searchParams.get("error");
    if (!code) return;
    const detail = searchParams.get("detail");
    const base = OAUTH_ERROR_MESSAGES[code] ?? "Sign-in failed";
    setError(detail ? `${base} (${detail})` : base);
  }, [searchParams]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await login(email, password);
      router.push("/dashboard");
      router.refresh();
    } catch (e) {
      setError(e instanceof ApiError ? "Invalid email or password" : "Login failed");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-surface">
      <SiteNav ctaHref="/signup" ctaLabel="Sign up" />
      <div className="flex flex-1 items-center justify-center px-6 py-16">
        <div className="w-full max-w-sm">
          <h1 className="font-serif text-3xl text-foreground mb-2">Log in</h1>
          <p className="text-muted text-[15px] mb-8 leading-relaxed">
            Dashboard access uses your account. Training scripts use API keys from Account.
          </p>

          <p className="text-xs text-muted mb-6 leading-relaxed border-l-2 border-border pl-3">
            Docker demo:{" "}
            <button
              type="button"
              className="text-foreground hover:underline"
              onClick={() => {
                setEmail("demo@faultline.local");
                setPassword("faultlinedemo");
              }}
            >
              demo@faultline.local
            </button>{" "}
            / faultlinedemo
          </p>

          <form onSubmit={handleSubmit} className="space-y-5">
            <label className="block text-sm">
              <span className="text-muted">Email</span>
              <input
                type="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="input-field"
              />
            </label>
            <label className="block text-sm">
              <span className="text-muted">Password</span>
              <input
                type="password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input-field"
              />
            </label>
            {error ? <p className="text-danger text-sm">{error}</p> : null}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Signing in…" : "Continue"}
            </Button>
          </form>

          <div className="mt-5 space-y-2">
            <a
              href="/api/auth/oauth/google"
              className="block w-full rounded-lg border border-border bg-surface-elevated px-4 py-2.5 text-center text-sm text-foreground no-underline hover:no-underline hover:bg-surface-2"
            >
              Continue with Google
            </a>
            <a
              href="/api/auth/oauth/github"
              className="block w-full rounded-lg border border-border bg-surface-elevated px-4 py-2.5 text-center text-sm text-foreground no-underline hover:no-underline hover:bg-surface-2"
            >
              Continue with GitHub
            </a>
          </div>

          <p className="text-sm text-muted mt-8">
            No account?{" "}
            <Link href="/signup" className="text-foreground font-medium">
              Sign up
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
