"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";

import { Alert } from "@/components/Alert";
import { Spinner } from "@/components/Spinner";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/AuthProvider";

function LoginForm() {
  const { status, login } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  // RouteGuard appends ?next= when it bounces an unauthenticated visitor.
  const next = searchParams.get("next") || "/claims";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // Someone already signed in has no business here.
  useEffect(() => {
    if (status === "authenticated") router.replace(next);
  }, [status, router, next]);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(email, password);
      router.replace(next);
    } catch (cause) {
      setError(
        cause instanceof ApiError
          ? cause.detail
          : "Something went wrong signing in. Please try again.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm">
      <h1 className="text-2xl font-semibold">Sign in</h1>
      <p className="mt-1 text-sm text-slate-500">
        Use the account you registered with.
      </p>

      <form onSubmit={handleSubmit} className="mt-6 space-y-4" noValidate>
        {error && <Alert variant="error">{error}</Alert>}

        <div>
          <label htmlFor="email" className="field-label">
            Email
          </label>
          <input
            id="email"
            name="email"
            type="email"
            autoComplete="email"
            required
            className="field-input"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            disabled={submitting}
          />
        </div>

        <div>
          <label htmlFor="password" className="field-label">
            Password
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="current-password"
            required
            className="field-input"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={submitting}
          />
        </div>

        <button type="submit" className="btn-primary w-full" disabled={submitting}>
          {submitting ? <Spinner label="Signing in" /> : "Sign in"}
        </button>
      </form>

      <p className="mt-6 text-sm text-slate-600">
        No account?{" "}
        <Link href="/register" className="font-medium text-brand-600 hover:underline">
          Create one
        </Link>
      </p>
    </div>
  );
}

/**
 * `useSearchParams` opts the subtree into client-side rendering, so Next
 * requires a Suspense boundary around it — without one, `next build` fails
 * while prerendering this route.
 */
export default function LoginPage() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-[40vh] items-center justify-center">
          <Spinner label="Loading sign-in" className="h-8 w-8" />
        </div>
      }
    >
      <LoginForm />
    </Suspense>
  );
}
