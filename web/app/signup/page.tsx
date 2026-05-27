"use client";

import { Button } from "@/components/ui/button";
import { SiteNav } from "@/components/SiteNav";
import { signup, ApiError } from "@/lib/api";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

export default function SignupPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      await signup(email, password);
      router.push("/dashboard");
      router.refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) {
        setError("An account with this email already exists");
      } else if (e instanceof ApiError && e.status === 400) {
        setError("Check email format and password (min 8 characters)");
      } else {
        setError("Signup failed");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen flex flex-col bg-surface">
      <SiteNav ctaHref="/login" ctaLabel="Log in" />
      <div className="flex flex-1 items-center justify-center px-6 py-16">
        <div className="w-full max-w-sm">
          <h1 className="font-serif text-3xl text-foreground mb-2">Sign up</h1>
          <p className="text-muted text-[15px] mb-8 leading-relaxed">
            Create an account, then add an API key for your training machines.
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
              <span className="text-muted">Password (8+ characters)</span>
              <input
                type="password"
                required
                minLength={8}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="input-field"
              />
            </label>
            {error ? <p className="text-danger text-sm">{error}</p> : null}
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? "Creating…" : "Create account"}
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
            Already have an account?{" "}
            <Link href="/login" className="text-foreground font-medium">
              Log in
            </Link>
          </p>
        </div>
      </div>
    </div>
  );
}
