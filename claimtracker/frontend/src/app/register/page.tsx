"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/Alert";
import { Spinner } from "@/components/Spinner";
import { ApiError, authApi } from "@/lib/api/client";
import { ROLES, type Role } from "@/lib/api/types";
import { useAuth } from "@/lib/auth/AuthProvider";

/**
 * The password rules mirror `RegisterRequest` in backend/app/schemas/auth.py
 * (>= 8 chars, one digit, one uppercase). They are checked here so the user
 * gets immediate feedback, and again on the server, which is authoritative.
 */
function validatePassword(password: string): string | null {
  if (password.length < 8) return "Use at least 8 characters.";
  if (!/\d/.test(password)) return "Include at least one digit.";
  if (!/[A-Z]/.test(password)) return "Include at least one uppercase letter.";
  return null;
}

export default function RegisterPage() {
  const { login } = useAuth();
  const router = useRouter();

  const [fullName, setFullName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>("user");
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    const passwordError = validatePassword(password);
    if (passwordError) {
      setFieldErrors({ password: passwordError });
      return;
    }
    setFieldErrors({});
    setSubmitting(true);

    try {
      await authApi.register({
        email,
        password,
        full_name: fullName,
        role,
      });
      // Registration does not return a token, so sign in straight away —
      // landing on the login page after a successful signup is a dead end.
      await login(email, password);
      router.replace("/claims");
    } catch (cause) {
      if (cause instanceof ApiError) {
        if (cause.fieldErrors.length > 0) {
          setFieldErrors(
            Object.fromEntries(
              cause.fieldErrors.map((item) => [item.field, item.message]),
            ),
          );
        }
        setError(cause.detail);
      } else {
        setError("Something went wrong creating your account. Please try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-sm">
      <h1 className="text-2xl font-semibold">Create an account</h1>
      <p className="mt-1 text-sm text-slate-500">
        Pick a role to see the matching parts of the app.
      </p>

      <form onSubmit={handleSubmit} className="mt-6 space-y-4" noValidate>
        {error && <Alert variant="error">{error}</Alert>}

        <div>
          <label htmlFor="full_name" className="field-label">
            Full name
          </label>
          <input
            id="full_name"
            name="full_name"
            type="text"
            autoComplete="name"
            required
            minLength={2}
            className="field-input"
            value={fullName}
            onChange={(event) => setFullName(event.target.value)}
            disabled={submitting}
            aria-invalid={Boolean(fieldErrors.full_name)}
            aria-describedby={fieldErrors.full_name ? "full_name-error" : undefined}
          />
          {fieldErrors.full_name && (
            <p id="full_name-error" className="field-error">
              {fieldErrors.full_name}
            </p>
          )}
        </div>

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
            aria-invalid={Boolean(fieldErrors.email)}
            aria-describedby={fieldErrors.email ? "email-error" : undefined}
          />
          {fieldErrors.email && (
            <p id="email-error" className="field-error">
              {fieldErrors.email}
            </p>
          )}
        </div>

        <div>
          <label htmlFor="password" className="field-label">
            Password
          </label>
          <input
            id="password"
            name="password"
            type="password"
            autoComplete="new-password"
            required
            className="field-input"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            disabled={submitting}
            aria-invalid={Boolean(fieldErrors.password)}
            aria-describedby="password-hint password-error"
          />
          <p id="password-hint" className="mt-1 text-xs text-slate-500">
            At least 8 characters, with one digit and one uppercase letter.
          </p>
          {fieldErrors.password && (
            <p id="password-error" className="field-error">
              {fieldErrors.password}
            </p>
          )}
        </div>

        <div>
          <label htmlFor="role" className="field-label">
            Role
          </label>
          <select
            id="role"
            name="role"
            className="field-input"
            value={role}
            onChange={(event) => setRole(event.target.value as Role)}
            disabled={submitting}
          >
            {ROLES.map((option) => (
              <option key={option} value={option}>
                {option}
              </option>
            ))}
          </select>
          <p className="mt-1 text-xs text-slate-500">
            Open registration of reviewers and admins is a demo convenience —
            a real deployment would invite them instead.
          </p>
        </div>

        <button type="submit" className="btn-primary w-full" disabled={submitting}>
          {submitting ? <Spinner label="Creating your account" /> : "Create account"}
        </button>
      </form>

      <p className="mt-6 text-sm text-slate-600">
        Already registered?{" "}
        <Link href="/login" className="font-medium text-brand-600 hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
