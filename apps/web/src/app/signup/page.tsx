"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useState } from "react";

import { useAuth } from "@/lib/auth-context";
import { ApiError } from "@/lib/api";

export default function SignupPage() {
  const router = useRouter();
  const { signup } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await signup(email, password);
      router.push("/");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Sign up failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-full w-full max-w-sm flex-1 flex-col justify-center px-6 py-12">
      <h1 className="mb-1 font-mono text-lg font-semibold">Create account</h1>
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
            minLength={8}
            autoComplete="new-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="w-full rounded-md border border-border bg-surface px-3 py-2 text-sm outline-none focus:border-accent"
          />
          <p className="mt-1 text-[10px] text-muted">At least 8 characters.</p>
        </div>

        {error && <p className="text-[11px] text-negative">{error}</p>}

        <button
          type="submit"
          disabled={submitting}
          className="w-full rounded-md bg-accent px-3 py-2 text-sm font-medium text-background disabled:opacity-60"
        >
          {submitting ? "Creating account…" : "Create account"}
        </button>
      </form>

      <p className="mt-4 text-xs text-muted">
        Already have an account?{" "}
        <Link href="/login" className="text-accent hover:underline">
          Sign in
        </Link>
      </p>
    </main>
  );
}
