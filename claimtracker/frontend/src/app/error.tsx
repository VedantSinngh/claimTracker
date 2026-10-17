"use client";

/**
 * Route-level error boundary. Next renders this when a client component in the
 * subtree throws during render — an API failure does not reach here, because
 * every page catches ApiError and shows an inline Alert instead.
 */
import { useEffect } from "react";

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surfaced in the browser console for debugging; a real deployment would
    // forward this to an error tracker.
    console.error("[ClaimTracker] unhandled render error:", error);
  }, [error]);

  return (
    <div className="mx-auto max-w-md py-16 text-center">
      <h1 className="text-2xl font-semibold">Something went wrong</h1>
      <p className="mt-2 text-sm text-slate-500">
        This page failed to render. Trying again often works; if it does not, the
        browser console has the details.
      </p>
      {error.digest && (
        <p className="mt-2 text-xs text-slate-400">Reference: {error.digest}</p>
      )}
      <button type="button" onClick={reset} className="btn-primary mt-6">
        Try again
      </button>
    </div>
  );
}
