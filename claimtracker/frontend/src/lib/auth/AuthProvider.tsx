"use client";

/**
 * src/lib/auth/AuthProvider.tsx
 * ──────────────────────────────
 * Session state for the whole app.
 *
 * On mount it calls `/auth/me` with whatever token is in storage. That one
 * round-trip is what makes the guards trustworthy: the role used for routing
 * comes from the backend's view of the token, not from anything the client
 * decoded or remembered. A 401 clears the token.
 *
 * `status` is a three-state machine — "loading" until `/auth/me` settles, then
 * "authenticated" or "anonymous". Guards must wait for "loading" to finish,
 * otherwise every protected page would flash a redirect on first paint.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

import { ApiError, authApi, clearToken, getToken, setToken } from "@/lib/api/client";
import type { Role, UserResponse } from "@/lib/api/types";

export type AuthStatus = "loading" | "authenticated" | "anonymous";

interface AuthContextValue {
  status: AuthStatus;
  user: UserResponse | null;
  /** Signs in, stores the token, and resolves with the signed-in user. */
  login: (email: string, password: string) => Promise<UserResponse>;
  logout: () => void;
  /** True when the user holds any of the given roles. */
  hasRole: (...roles: Role[]) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<AuthStatus>("loading");
  const [user, setUser] = useState<UserResponse | null>(null);

  // Resolve the stored token exactly once on mount.
  useEffect(() => {
    const token = getToken();
    if (!token) {
      setStatus("anonymous");
      return;
    }

    const controller = new AbortController();
    let active = true;

    authApi
      .me(controller.signal)
      .then((me) => {
        if (!active) return;
        setUser(me);
        setStatus("authenticated");
      })
      .catch((error: unknown) => {
        if (!active) return;
        if (error instanceof DOMException && error.name === "AbortError") return;
        // An expired or tampered token is worth discarding. A network blip is
        // not, but we still cannot claim a session, so both end as anonymous.
        if (error instanceof ApiError && error.isAuthError) clearToken();
        setUser(null);
        setStatus("anonymous");
      });

    return () => {
      active = false;
      controller.abort();
    };
  }, []);

  const login = useCallback(async (email: string, password: string) => {
    const token = await authApi.login({ email, password });
    setToken(token.access_token);
    // Re-fetch rather than trusting the login payload, so `user` is always
    // the same shape from the same source.
    const me = await authApi.me();
    setUser(me);
    setStatus("authenticated");
    return me;
  }, []);

  const logout = useCallback(() => {
    clearToken();
    setUser(null);
    setStatus("anonymous");
  }, []);

  const hasRole = useCallback(
    (...roles: Role[]) => (user ? roles.includes(user.role) : false),
    [user],
  );

  const value = useMemo<AuthContextValue>(
    () => ({ status, user, login, logout, hasRole }),
    [status, user, login, logout, hasRole],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (context === null) {
    throw new Error("useAuth must be used inside <AuthProvider>.");
  }
  return context;
}
