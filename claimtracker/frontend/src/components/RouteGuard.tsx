"use client";

/**
 * src/components/RouteGuard.tsx
 * ──────────────────────────────
 * Client-side role gate.
 *
 * This is a UX affordance, not a security boundary — the token lives in
 * localStorage and every page is a client component, so there is no server
 * session to check. The real enforcement is `require_role` on the FastAPI
 * routers, which is why the guard never tries to hide data the API would have
 * returned anyway: it only decides which page to show.
 *
 * Three cases:
 *   loading        → spinner (never redirect, or protected pages flash)
 *   anonymous      → bounce to /login, remembering where we were going
 *   wrong role     → explain it, rather than redirecting into a loop
 */
import { useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { Alert } from "@/components/Alert";
import { Spinner } from "@/components/Spinner";
import type { Role } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/AuthProvider";

export function RouteGuard({
  children,
  roles,
}: {
  children: ReactNode;
  /** Omit to require only that the viewer is signed in. */
  roles?: Role[];
}) {
  const { status, user } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status !== "anonymous") return;
    const next =
      typeof window === "undefined"
        ? ""
        : `?next=${encodeURIComponent(window.location.pathname)}`;
    router.replace(`/login${next}`);
  }, [status, router]);

  if (status === "loading") {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <Spinner label="Checking your session" className="h-8 w-8" />
      </div>
    );
  }

  if (status === "anonymous") {
    // The effect above is redirecting; render nothing rather than a flash.
    return null;
  }

  if (roles && user && !roles.includes(user.role)) {
    return (
      <div className="mx-auto max-w-xl py-12">
        <Alert variant="warning" title="You do not have access to this page">
          <p>
            This page is for{" "}
            {roles.map((role, index) => (
              <span key={role}>
                {index > 0 && (index === roles.length - 1 ? " or " : ", ")}
                <strong>{role}</strong>
              </span>
            ))}
            . You are signed in as <strong>{user.role}</strong>.
          </p>
        </Alert>
      </div>
    );
  }

  return <>{children}</>;
}
