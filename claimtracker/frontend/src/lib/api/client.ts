/**
 * src/lib/api/client.ts
 * ──────────────────────
 * The single place that talks to the FastAPI backend.
 *
 * Everything goes through `request()` so that auth headers, error shaping and
 * JSON handling exist exactly once. Nothing else in the app calls `fetch`.
 *
 * Error contract: every failure throws an `ApiError` carrying the HTTP status
 * and the backend's `detail`. Pages can therefore branch on `status` (401 →
 * sign in again, 403 → not your role, 422 → show field errors) instead of
 * parsing message strings.
 *
 * Token storage: the JWT lives in localStorage rather than an httpOnly cookie.
 * That is a deliberate trade-off for a portfolio build — it keeps the backend
 * stateless and CORS-simple — but it is XSS-exposed, so a production
 * deployment should move to an httpOnly, SameSite=Strict cookie set by the
 * backend. Noted in docs/RESPONSIBLE_AI.md.
 */
import type {
  AnalyticsSummaryResponse,
  ClaimListResponse,
  ClaimResponse,
  ClaimStatus,
  ClaimSubmitFields,
  ExclusionCreateRequest,
  ExclusionListResponse,
  ExclusionResponse,
  HandbookListResponse,
  HandbookResponse,
  HealthResponse,
  LoginRequest,
  RegisterRequest,
  ReviewCreateRequest,
  ReviewResponse,
  TokenResponse,
  UserResponse,
} from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL?.replace(/\/+$/, "") ?? "http://localhost:8000";

const TOKEN_KEY = "claimtracker.token";

// ── Token storage ────────────────────────────────────────────────────────────

/** Reads the stored JWT. Returns null during SSR and in private-mode failures. */
export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* storage blocked — the session simply will not survive a reload */
  }
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* nothing to do */
  }
}

// ── Errors ───────────────────────────────────────────────────────────────────

/** Field-level errors, as FastAPI/Pydantic returns them on a 422. */
export interface FieldError {
  field: string;
  message: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly detail: string;
  readonly fieldErrors: FieldError[];

  constructor(status: number, detail: string, fieldErrors: FieldError[] = []) {
    super(detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
    this.fieldErrors = fieldErrors;
  }

  /** True when the caller should be sent back to the sign-in page. */
  get isAuthError(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }
}

/**
 * FastAPI's error bodies come in three shapes:
 *   {detail: "message"}                                  — our handlers
 *   {detail: "message", errors: {...}}                    — ValidationError
 *   {detail: [{loc: [...], msg: "...", type: "..."}]}     — Pydantic 422
 * This flattens all three into a message plus optional field errors.
 */
function parseErrorBody(
  status: number,
  body: unknown,
  fallback: string,
): ApiError {
  if (typeof body !== "object" || body === null) {
    return new ApiError(status, fallback);
  }

  const detail = (body as { detail?: unknown }).detail;

  if (typeof detail === "string") {
    return new ApiError(status, detail);
  }

  if (Array.isArray(detail)) {
    const fieldErrors: FieldError[] = detail.map((item) => {
      const loc = Array.isArray((item as { loc?: unknown }).loc)
        ? ((item as { loc: unknown[] }).loc as unknown[])
        : [];
      // loc is like ["body", "claim_amount"]; the last entry is the field.
      const field = loc.length > 0 ? String(loc[loc.length - 1]) : "";
      const msg = String((item as { msg?: unknown }).msg ?? fallback);
      return { field, message: msg };
    });
    const summary =
      fieldErrors.length === 1
        ? `${fieldErrors[0].field}: ${fieldErrors[0].message}`
        : `${fieldErrors.length} fields are invalid.`;
    return new ApiError(status, summary, fieldErrors);
  }

  return new ApiError(status, fallback);
}

// ── Core request ─────────────────────────────────────────────────────────────

interface RequestOptions {
  method?: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  /** JSON body. Mutually exclusive with `formData`. */
  body?: unknown;
  /** Multipart body, for the two file-upload endpoints. */
  formData?: FormData;
  /** Set false for the auth endpoints, which must not send a stale token. */
  auth?: boolean;
  signal?: AbortSignal;
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, formData, auth = true, signal } = options;

  const headers: Record<string, string> = {};
  if (auth) {
    const token = getToken();
    if (token) headers.Authorization = `Bearer ${token}`;
  }
  // Content-Type is set only for JSON: the browser must choose the multipart
  // boundary itself, so setting it for FormData would corrupt the request.
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      method,
      headers,
      body: formData ?? (body !== undefined ? JSON.stringify(body) : undefined),
      signal,
    });
  } catch (cause) {
    // A network-level failure (backend down, DNS, CORS preflight rejected)
    // never reaches the status checks below, so give it a usable message.
    if (cause instanceof DOMException && cause.name === "AbortError") throw cause;
    throw new ApiError(
      0,
      `Could not reach the API at ${API_BASE_URL}. Is the backend running?`,
    );
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let parsed: unknown = undefined;
  if (text) {
    try {
      parsed = JSON.parse(text);
    } catch {
      parsed = undefined;
    }
  }

  if (!response.ok) {
    throw parseErrorBody(
      response.status,
      parsed,
      `Request failed with status ${response.status}.`,
    );
  }

  return parsed as T;
}

// ── Auth ─────────────────────────────────────────────────────────────────────

export const authApi = {
  register(payload: RegisterRequest): Promise<UserResponse> {
    return request<UserResponse>("/auth/register", {
      method: "POST",
      body: payload,
      auth: false,
    });
  },

  login(payload: LoginRequest): Promise<TokenResponse> {
    return request<TokenResponse>("/auth/login", {
      method: "POST",
      body: payload,
      auth: false,
    });
  },

  me(signal?: AbortSignal): Promise<UserResponse> {
    return request<UserResponse>("/auth/me", { signal });
  },
};

// ── Claims ───────────────────────────────────────────────────────────────────

export const claimsApi = {
  /**
   * Submits the form and the bill in one multipart request. The backend
   * returns immediately with status PENDING and runs the AI pipeline as a
   * background task, so callers should poll `get` afterwards.
   */
  submit(fields: ClaimSubmitFields, billFile: File): Promise<ClaimResponse> {
    const formData = new FormData();
    formData.append("patient_name", fields.patient_name);
    formData.append("claim_item", fields.claim_item);
    formData.append("reason", fields.reason);
    formData.append("address", fields.address);
    formData.append("date_of_treatment", fields.date_of_treatment);
    formData.append("medical_facility", fields.medical_facility);
    formData.append("claim_amount", String(fields.claim_amount));
    if (fields.description) formData.append("description", fields.description);
    formData.append("bill_file", billFile);

    return request<ClaimResponse>("/claims", { method: "POST", formData });
  },

  list(
    params: { status?: ClaimStatus | ""; page?: number; pageSize?: number } = {},
    signal?: AbortSignal,
  ): Promise<ClaimListResponse> {
    const query = new URLSearchParams();
    if (params.status) query.set("status", params.status);
    query.set("page", String(params.page ?? 1));
    query.set("page_size", String(params.pageSize ?? 20));
    return request<ClaimListResponse>(`/claims?${query.toString()}`, { signal });
  },

  get(claimId: string, signal?: AbortSignal): Promise<ClaimResponse> {
    return request<ClaimResponse>(`/claims/${claimId}`, { signal });
  },

  review(claimId: string, payload: ReviewCreateRequest): Promise<ReviewResponse> {
    return request<ReviewResponse>(`/claims/${claimId}/review`, {
      method: "POST",
      body: payload,
    });
  },
};

// ── Exclusions (admin) ───────────────────────────────────────────────────────

export const exclusionsApi = {
  list(
    params: { skip?: number; limit?: number } = {},
    signal?: AbortSignal,
  ): Promise<ExclusionListResponse> {
    const query = new URLSearchParams({
      skip: String(params.skip ?? 0),
      limit: String(params.limit ?? 50),
    });
    return request<ExclusionListResponse>(`/exclusions?${query.toString()}`, {
      signal,
    });
  },

  create(payload: ExclusionCreateRequest): Promise<ExclusionResponse> {
    return request<ExclusionResponse>("/exclusions", {
      method: "POST",
      body: payload,
    });
  },

  remove(exclusionId: string): Promise<void> {
    return request<void>(`/exclusions/${exclusionId}`, { method: "DELETE" });
  },
};

// ── Handbooks ────────────────────────────────────────────────────────────────

export const handbooksApi = {
  /** Admin only. Ingestion is synchronous and can take a while on a big PDF. */
  upload(versionTag: string, file: File): Promise<HandbookResponse> {
    const formData = new FormData();
    formData.append("version_tag", versionTag);
    formData.append("handbook_file", file);
    return request<HandbookResponse>("/handbooks", { method: "POST", formData });
  },

  list(signal?: AbortSignal): Promise<HandbookListResponse> {
    return request<HandbookListResponse>("/handbooks", { signal });
  },
};

// ── Analytics (admin) ────────────────────────────────────────────────────────

export const analyticsApi = {
  summary(signal?: AbortSignal): Promise<AnalyticsSummaryResponse> {
    return request<AnalyticsSummaryResponse>("/analytics/summary", { signal });
  },
};

// ── Health ───────────────────────────────────────────────────────────────────

export const healthApi = {
  check(signal?: AbortSignal): Promise<HealthResponse> {
    return request<HealthResponse>("/health", { auth: false, signal });
  },
};

/** Exported for tests only. */
export const __internal = { request, parseErrorBody, TOKEN_KEY };
