/**
 * src/lib/api/types.ts
 * ─────────────────────
 * TypeScript mirrors of the backend's Pydantic v2 schemas.
 *
 * Hand-written rather than generated from the OpenAPI document, because the
 * schema set is small and stable, and hand-written types let us encode things
 * the JSON Schema loses — notably `ClaimStatus` and `Role` as unions rather
 * than bare strings, which makes exhaustive switches on status type-check.
 *
 * If a backend schema changes, change it here too. The source files are:
 *   backend/app/schemas/{auth,claim,review,exclusion,handbook,analytics}.py
 *
 * Note on numbers: the backend serialises `Decimal` (claim_amount,
 * total_amount_extracted) as a JSON string, not a number. They are typed
 * `string` here and must go through `parseAmount` before arithmetic — see
 * src/lib/format.ts.
 */

// ── Shared unions ────────────────────────────────────────────────────────────

/** Mirrors claim_status_enum. Terminal statuses are the last three. */
export const CLAIM_STATUSES = [
  "PENDING",
  "PROCESSING",
  "ACCEPTED",
  "REJECTED",
  "NEEDS_REVIEW",
] as const;
export type ClaimStatus = (typeof CLAIM_STATUSES)[number];

/** A claim in one of these is still moving; the detail page polls while so. */
export const IN_FLIGHT_STATUSES: readonly ClaimStatus[] = ["PENDING", "PROCESSING"];

/** Mirrors the seeded rows in the `roles` table. */
export const ROLES = ["user", "reviewer", "admin"] as const;
export type Role = (typeof ROLES)[number];

export const REVIEW_OUTCOMES = ["APPROVED", "REJECTED", "OVERRIDE"] as const;
export type ReviewOutcome = (typeof REVIEW_OUTCOMES)[number];

/** Statuses a reviewer may set via an OVERRIDE. */
export const OVERRIDE_STATUSES = ["ACCEPTED", "REJECTED", "NEEDS_REVIEW"] as const;
export type OverrideStatus = (typeof OVERRIDE_STATUSES)[number];

// ── Auth ─────────────────────────────────────────────────────────────────────

export interface RegisterRequest {
  email: string;
  password: string;
  full_name: string;
  role?: Role;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user_id: string;
  role: Role;
}

export interface UserResponse {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  is_active: boolean;
}

// ── Claims ───────────────────────────────────────────────────────────────────

export interface ClaimDocumentResponse {
  id: string;
  file_name: string;
  mime_type: string;
  uploaded_at: string;
}

export interface ExtractedFieldsResponse {
  patient_name_extracted: string | null;
  diagnosis: string | null;
  facility_extracted: string | null;
  date_extracted: string | null;
  itemised_charges: Record<string, unknown> | null;
  total_amount_extracted: string | null;
  llm_model: string | null;
  prompt_version: string | null;
  extracted_at: string;
}

/**
 * A clause the model cited. The backend types this as `List[Any]`, and the
 * decision prompt asks for `{clause, text}` objects — but an LLM can return
 * a bare string, so the UI must tolerate both.
 */
export type CitedClause = { clause?: string; text?: string } | string;

export interface DecisionResponse {
  id: string;
  outcome: ClaimStatus;
  reason: string | null;
  cited_clauses: CitedClause[] | null;
  executive_summary: string | null;
  confidence_score: number | null;
  model_name: string | null;
  prompt_version: string | null;
  decided_at: string;
}

export interface ClaimResponse {
  id: string;
  user_id: string;
  patient_name: string;
  claim_item: string;
  reason: string;
  address: string;
  date_of_treatment: string;
  medical_facility: string;
  claim_amount: string;
  description: string | null;
  status: ClaimStatus;
  confidence_score: number | null;
  created_at: string;
  updated_at: string;
  documents: ClaimDocumentResponse[];
  extracted_fields: ExtractedFieldsResponse | null;
  decisions: DecisionResponse[];
}

export interface ClaimListResponse {
  items: ClaimResponse[];
  total: number;
  page: number;
  page_size: number;
}

/** The multipart submit form. `bill_file` is sent alongside as the file part. */
export interface ClaimSubmitFields {
  patient_name: string;
  claim_item: string;
  reason: string;
  address: string;
  /** YYYY-MM-DD */
  date_of_treatment: string;
  medical_facility: string;
  claim_amount: number;
  description?: string;
}

// ── Reviews ──────────────────────────────────────────────────────────────────

export interface ReviewCreateRequest {
  outcome: ReviewOutcome;
  comment?: string;
  /** Required when outcome is OVERRIDE; ignored otherwise. */
  new_status?: OverrideStatus;
}

export interface ReviewResponse {
  id: string;
  claim_id: string;
  reviewer_id: string;
  outcome: ReviewOutcome;
  comment: string | null;
  previous_status: ClaimStatus;
  new_status: ClaimStatus;
  reviewed_at: string;
}

// ── Exclusions ───────────────────────────────────────────────────────────────

export interface ExclusionCreateRequest {
  term: string;
  description?: string;
}

export interface ExclusionResponse {
  id: string;
  term: string;
  description: string | null;
  is_active: boolean;
  created_at: string;
}

export interface ExclusionListResponse {
  items: ExclusionResponse[];
  total: number;
}

// ── Handbooks ────────────────────────────────────────────────────────────────

export interface HandbookResponse {
  id: string;
  version_tag: string;
  chunk_count: number | null;
  is_active: boolean;
  uploaded_at: string;
}

export interface HandbookListResponse {
  items: HandbookResponse[];
  total: number;
}

// ── Analytics ────────────────────────────────────────────────────────────────

/**
 * The analytics endpoint returns raw SQL rows (`List[Dict[str, Any]]`), so the
 * shapes below describe what the queries in db/analytics.sql actually select
 * rather than anything the backend enforces. Numeric columns arrive as strings
 * where the SQL produces NUMERIC.
 */
export interface MonthlyStatusRow {
  month: string;
  status: Extract<ClaimStatus, "ACCEPTED" | "REJECTED">;
  count: number;
}

export interface RejectionReasonRow {
  reason: string;
  rejection_count: number;
  rank: number;
}

export interface ProcessingTimeRow {
  status: ClaimStatus;
  avg_seconds: string | number | null;
}

export interface ClaimsPerUserRow {
  full_name: string;
  email: string;
  total_claims: number;
  accepted: number;
  rejected: number;
}

export interface AnalyticsSummaryResponse {
  approval_rejection_by_month: MonthlyStatusRow[];
  top_rejection_reasons: RejectionReasonRow[];
  avg_processing_time_by_status: ProcessingTimeRow[];
  claims_per_user: ClaimsPerUserRow[];
}

// ── Health ───────────────────────────────────────────────────────────────────

export interface HealthResponse {
  status: string;
  version: string;
}
