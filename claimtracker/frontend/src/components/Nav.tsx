"use client";

/**
 * src/components/Nav.tsx
 * ───────────────────────
 * Top bar. The link set is derived from the signed-in user's role, so a plain
 * user never sees the reviewer queue or the admin pages. That is presentation
 * only — the API guards are what actually enforce it.
 */
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useState } from "react";

import type { Role } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/AuthProvider";

interface NavLink {
  href: string;
  label: string;
  /** Omit to show for every signed-in user. */
  roles?: Role[];
}

const LINKS: NavLink[] = [
  { href: "/claims", label: "My claims" },
  { href: "/claims/new", label: "Submit a claim" },
  { href: "/reviews", label: "Review queue", roles: ["reviewer", "admin"] },
  { href: "/admin/handbook", label: "Handbook", roles: ["admin"] },
  { href: "/admin/exclusions", label: "Exclusions", roles: ["admin"] },
  // The analytics dashboard is added in Phase 8, together with its page.
];

export function Nav() {
  const { status, user, logout, hasRole } = useAuth();
  const pathname = usePathname();
  const router = useRouter();
  const [menuOpen, setMenuOpen] = useState(false);

  const visible = LINKS.filter((link) => !link.roles || hasRole(...link.roles));

  function handleLogout() {
    logout();
    setMenuOpen(false);
    router.push("/login");
  }

  function isActive(href: string): boolean {
    // /claims must not light up while on /claims/new.
    if (href === "/claims") return pathname === "/claims";
    return pathname === href || pathname.startsWith(`${href}/`);
  }

  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex max-w-6xl items-center gap-4 px-4 py-3 sm:px-6 lg:px-8">
        <Link href="/" className="flex items-center gap-2 font-semibold text-slate-900">
          <span
            aria-hidden="true"
            className="grid h-7 w-7 place-items-center rounded bg-brand-500 text-sm text-white"
          >
            C
          </span>
          ClaimTracker
        </Link>

        {status === "authenticated" && (
          <>
            {/* Desktop links */}
            <nav aria-label="Main" className="ml-4 hidden md:block">
              <ul className="flex items-center gap-1">
                {visible.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      aria-current={isActive(link.href) ? "page" : undefined}
                      className={`rounded-md px-3 py-1.5 text-sm transition ${
                        isActive(link.href)
                          ? "bg-brand-50 font-medium text-brand-700"
                          : "text-slate-600 hover:bg-slate-100"
                      }`}
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>

            <div className="ml-auto flex items-center gap-3">
              <span className="hidden text-sm text-slate-500 sm:inline">
                {user?.full_name}
                <span className="ml-2 rounded bg-slate-100 px-1.5 py-0.5 text-xs uppercase tracking-wide text-slate-600">
                  {user?.role}
                </span>
              </span>
              <button type="button" onClick={handleLogout} className="btn-secondary">
                Sign out
              </button>
              <button
                type="button"
                className="btn-secondary md:hidden"
                aria-expanded={menuOpen}
                aria-controls="mobile-nav"
                onClick={() => setMenuOpen((open) => !open)}
              >
                Menu
              </button>
            </div>
          </>
        )}

        {status === "anonymous" && (
          <div className="ml-auto flex items-center gap-2">
            <Link href="/login" className="btn-secondary">
              Sign in
            </Link>
            <Link href="/register" className="btn-primary">
              Create account
            </Link>
          </div>
        )}
      </div>

      {/* Mobile links */}
      {status === "authenticated" && menuOpen && (
        <nav id="mobile-nav" aria-label="Main" className="border-t border-slate-200 md:hidden">
          <ul className="space-y-1 px-4 py-3">
            {visible.map((link) => (
              <li key={link.href}>
                <Link
                  href={link.href}
                  onClick={() => setMenuOpen(false)}
                  aria-current={isActive(link.href) ? "page" : undefined}
                  className={`block rounded-md px-3 py-2 text-sm ${
                    isActive(link.href)
                      ? "bg-brand-50 font-medium text-brand-700"
                      : "text-slate-700 hover:bg-slate-100"
                  }`}
                >
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      )}
    </header>
  );
}
