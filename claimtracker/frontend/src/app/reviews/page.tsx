"use client";

/**
 * src/app/reviews/page.tsx
 * ─────────────────────────
 * The reviewer queue: claims the pipeline would not decide on its own.
 *
 * Defaults to NEEDS_REVIEW, which is what the confidence threshold and every
 * ambiguous validator outcome route to. A reviewer can also pull up already
 * ACCEPTED or REJECTED claims to override them, which the backend allows
 * (`ReviewService` accepts any of those three as a previous status).
 *
 * Every action requires a comment. The override is the audit trail's reason
 * for overruling the model, so an unexplained one is worse than none.
 */
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { Alert } from "@/components/Alert";
import { EmptyState } from "@/components/EmptyState";
import { RouteGuard } from "@/components/RouteGuard";
import { Spinner } from "@/components/Spinner";
import { StatusBadge } from "@/components/StatusBadge";
import { ApiError, claimsApi } from "@/lib/api/client";
import {
  OVERRIDE_STATUSES,
  type ClaimResponse,
  type ClaimStatus,
  type OverrideStatus,
  type ReviewOutcome,
} from "@/lib/api/types";
import { formatConfidence, formatCurrency, formatDate, humaniseStatus } from "@/lib/format";

/** Statuses a reviewer can act on, per ReviewService.submit_review. */
const REVIEWABLE: ClaimStatus[] = ["NEEDS_REVIEW", "ACCEPTED", "REJECTED"];

function ReviewCard({
  claim,
  onReviewed,
}: {
  claim: ClaimResponse;
  onReviewed: () => void;
}) {
  const [outcome, setOutcome] = useState<ReviewOutcome>("APPROVED");
  const [newStatus, setNewStatus] = useState<OverrideStatus>("ACCEPTED");
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // `decisions` comes back in no guaranteed order, so pick the newest rather
  // than whatever the join happened to put first.
  const latest =
    [...claim.decisions].sort(
      (a, b) => new Date(b.decided_at).getTime() - new Date(a.decided_at).getTime(),
    )[0] ?? null;

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    if (!comment.trim()) {
      setError("Add a comment explaining the decision — it goes into the audit log.");
      return;
    }
    setSubmitting(true);
    try {
      await claimsApi.review(claim.id, {
        outcome,
        comment: comment.trim(),
        // Only meaningful for OVERRIDE; the backend ignores it otherwise.
        new_status: outcome === "OVERRIDE" ? newStatus : undefined,
      });
      onReviewed();
    } catch (cause) {
      setError(
        cause instanceof ApiError ? cause.detail : "Could not record the review.",
      );
      setSubmitting(false);
    }
  }

  return (
    <li className="card">
      <div className="card-header flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="font-medium text-slate-900">
            <Link href={`/claims/${claim.id}`} className="hover:underline">
              {claim.claim_item} — {claim.patient_name}
            </Link>
          </h3>
          <p className="mt-0.5 text-xs text-slate-500">
            {claim.medical_facility} · {formatDate(claim.date_of_treatment)} ·{" "}
            {formatCurrency(claim.claim_amount)}
          </p>
        </div>
        <div className="text-right">
          <StatusBadge status={claim.status} />
          {claim.confidence_score !== null && (
            <p className="mt-1 text-xs text-slate-500">
              Confidence {formatConfidence(claim.confidence_score)}
            </p>
          )}
        </div>
      </div>

      <div className="px-5 py-4">
        {latest?.reason && (
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
              Why it was flagged
            </p>
            <p className="mt-1 text-sm text-slate-700">{latest.reason}</p>
          </div>
        )}

        <form onSubmit={handleSubmit} className="mt-4 space-y-3" noValidate>
          {error && <Alert variant="error">{error}</Alert>}

          <fieldset>
            <legend className="field-label">Decision</legend>
            <div className="flex flex-wrap gap-4">
              {(["APPROVED", "REJECTED", "OVERRIDE"] as ReviewOutcome[]).map((option) => (
                <label key={option} className="flex items-center gap-2 text-sm">
                  <input
                    type="radio"
                    name={`outcome-${claim.id}`}
                    value={option}
                    checked={outcome === option}
                    onChange={() => setOutcome(option)}
                    disabled={submitting}
                    className="h-4 w-4 text-brand-500"
                  />
                  {option === "APPROVED"
                    ? "Approve"
                    : option === "REJECTED"
                      ? "Reject"
                      : "Override to…"}
                </label>
              ))}
            </div>
          </fieldset>

          {outcome === "OVERRIDE" && (
            <div>
              <label htmlFor={`new-status-${claim.id}`} className="field-label">
                New status
              </label>
              <select
                id={`new-status-${claim.id}`}
                className="field-input sm:max-w-xs"
                value={newStatus}
                onChange={(event) => setNewStatus(event.target.value as OverrideStatus)}
                disabled={submitting}
              >
                {OVERRIDE_STATUSES.map((option) => (
                  <option key={option} value={option}>
                    {humaniseStatus(option)}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label htmlFor={`comment-${claim.id}`} className="field-label">
              Comment
            </label>
            <textarea
              id={`comment-${claim.id}`}
              rows={2}
              required
              className="field-input"
              placeholder="What did you check, and why does it change the outcome?"
              value={comment}
              onChange={(event) => setComment(event.target.value)}
              disabled={submitting}
              aria-describedby={`comment-hint-${claim.id}`}
            />
            <p id={`comment-hint-${claim.id}`} className="mt-1 text-xs text-slate-500">
              Recorded against your user in the audit log.
            </p>
          </div>

          <div className="flex items-center gap-3">
            <button type="submit" className="btn-primary" disabled={submitting}>
              {submitting ? <Spinner label="Recording review" /> : "Record review"}
            </button>
            <Link href={`/claims/${claim.id}`} className="btn-secondary">
              Open full claim
            </Link>
          </div>
        </form>
      </div>
    </li>
  );
}

function ReviewQueue() {
  const [status, setStatus] = useState<ClaimStatus>("NEEDS_REVIEW");
  const [claims, setClaims] = useState<ClaimResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await claimsApi.list({ status, page: 1, pageSize: 50 });
      setClaims(result.items);
      setError(null);
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.detail : "Could not load the queue.");
    } finally {
      setLoading(false);
    }
  }, [status]);

  useEffect(() => {
    void load();
  }, [load]);

  function handleReviewed() {
    setNotice("Review recorded.");
    void load();
  }

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Review queue</h1>
          <p className="mt-1 text-sm text-slate-500">
            Claims the pipeline would not decide on its own, plus anything you want
            to override.
          </p>
        </div>
        <div>
          <label htmlFor="queue-status" className="field-label">
            Showing
          </label>
          <select
            id="queue-status"
            className="field-input"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as ClaimStatus);
              setNotice(null);
            }}
          >
            {REVIEWABLE.map((option) => (
              <option key={option} value={option}>
                {humaniseStatus(option)}
              </option>
            ))}
          </select>
        </div>
      </div>

      {notice && (
        <div className="mt-6">
          <Alert variant="success">{notice}</Alert>
        </div>
      )}

      {error && (
        <div className="mt-6">
          <Alert variant="error" title="Could not load the queue">
            {error}
          </Alert>
        </div>
      )}

      {loading && (
        <div className="mt-10 flex justify-center">
          <Spinner label="Loading the queue" className="h-8 w-8" />
        </div>
      )}

      {!loading && claims.length === 0 && (
        <div className="mt-6">
          <EmptyState
            title={`Nothing ${humaniseStatus(status).toLowerCase()}`}
            description={
              status === "NEEDS_REVIEW"
                ? "The queue is clear — every claim was decided automatically."
                : "No claims with this status."
            }
          />
        </div>
      )}

      {!loading && claims.length > 0 && (
        <ul className="mt-6 space-y-4">
          {claims.map((claim) => (
            <ReviewCard key={claim.id} claim={claim} onReviewed={handleReviewed} />
          ))}
        </ul>
      )}
    </>
  );
}

export default function ReviewsPage() {
  return (
    <RouteGuard roles={["reviewer", "admin"]}>
      <ReviewQueue />
    </RouteGuard>
  );
}
