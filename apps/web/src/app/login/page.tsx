"use client";

import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Suspense, useState } from "react";

import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/api";

/**
 * Phase 16.1 (§1): the real sign-in UI. `?next=` (set by proxy.ts when it
 * redirects an unauthenticated request) is honored on success -- signing
 * in returns the user to whatever page they actually wanted, not always
 * the app root. `useSearchParams()` requires a Suspense boundary for
 * static prerendering (Next.js's own requirement, same pattern TopNav
 * already uses) -- split into an outer default export and an inner
 * client component so the boundary wraps only the part that needs it.
 */
function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await login(email, password);
      const next = searchParams.get("next");
      router.push(next && next.startsWith("/") ? next : "/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign in failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-full w-full max-w-sm flex-1 flex-col justify-center px-6 py-12">
      <h1 className="mb-1 font-mono text-lg font-semibold">Sign in</h1>
      <p className="mb-6 text-xs text-muted">AI Market Desk</p>

      <form onSubmit={handleSubmit} className="space-y-3">
        <div>
          <label htmlFor="email" className="mb-1 block text-[11px] uppercase tracking-wide text-muted">
            Email
          </label>
          <input
            id="email"
            type="email"
            required
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
          />
        </div>
        <div>
          <label htmlFor="password" className="mb-1 block text-[11px] uppercase tracking-wide text-muted">
            Password
          </label>
          <input
            id="password"
            type="password"
            required
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
          />
        </div>

        {error && <p className="text-[11px] text-negative">{error}</p>}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-accent px-3 py-2 text-sm font-medium text-background disabled:opacity-60"
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <p className="mt-4 text-xs text-muted">
        Don&apos;t have an account?{" "}
        <Link href="/signup" className="text-accent hover:underline">
          Sign up
        </Link>
      </p>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginForm />
    </Suspense>
  );
}
