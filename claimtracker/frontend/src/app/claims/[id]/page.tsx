"use client";

/**
 * src/app/claims/[id]/page.tsx
 * ─────────────────────────────
 * Claim detail: the executive summary, what the OCR/LLM extracted, the
 * handbook clauses the decision cited, and the timeline of decisions.
 *
 * Polls while the claim is PENDING or PROCESSING, because the pipeline runs as
 * a FastAPI BackgroundTask with no push channel. Polling stops on a terminal
 * status, and also after MAX_POLLS so a claim wedged in PROCESSING cannot spin
 * the browser forever — it says so instead.
 *
 * "No decision without evidence" is a product rule, so when a decision has no
 * cited clauses this page says that explicitly rather than rendering nothing.
 */
import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";

import { Alert } from "@/components/Alert";
import { RouteGuard } from "@/components/RouteGuard";
import { Spinner } from "@/components/Spinner";
import { StatusBadge } from "@/components/StatusBadge";
import { ApiError, claimsApi } from "@/lib/api/client";
import { IN_FLIGHT_STATUSES, type ClaimResponse } from "@/lib/api/types";
import {
  formatConfidence,
  formatCurrency,
  formatDate,
  formatDateTime,
  normaliseClause,
  parseExecutiveSummary,
} from "@/lib/format";

const POLL_INTERVAL_MS = 3000;
/** ~2 minutes of polling; the pipeline should finish in seconds. */
const MAX_POLLS = 40;

function DetailRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 py-2 sm:flex-row sm:gap-4">
      <dt className="w-48 shrink-0 text-sm text-slate-500">{label}</dt>
      <dd className="text-sm text-slate-900">{children}</dd>
    </div>
  );
}

function ClaimDetail({ claimId }: { claimId: string }) {
  const [claim, setClaim] = useState<ClaimResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pollCount, setPollCount] = useState(0);
  const [pollExhausted, setPollExhausted] = useState(false);

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(
    async (options: { silent?: boolean } = {}) => {
      if (!options.silent) setLoading(true);
      try {
        const result = await claimsApi.get(claimId);
        setClaim(result);
        setError(null);
      } catch (cause) {
        if (cause instanceof ApiError) {
          // A 404 here also covers "not yours" — the service returns None for
          // another user's claim rather than leaking its existence.
          setError(
            cause.status === 404
              ? "This claim does not exist, or you do not have access to it."
              : cause.detail,
          );
        } else {
          setError("Could not load this claim.");
        }
      } finally {
        if (!options.silent) setLoading(false);
      }
    },
    [claimId],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const inFlight = claim ? IN_FLIGHT_STATUSES.includes(claim.status) : false;

  useEffect(() => {
    if (!inFlight || pollExhausted) return;
    if (pollCount >= MAX_POLLS) {
      setPollExhausted(true);
      return;
    }
    timerRef.current = setTimeout(() => {
      setPollCount((count) => count + 1);
      void load({ silent: true });
    }, POLL_INTERVAL_MS);
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [inFlight, pollCount, pollExhausted, load]);

  if (loading && !claim) {
    return (
      <div className="flex min-h-[40vh] items-center justify-center">
        <Spinner label="Loading claim" className="h-8 w-8" />
      </div>
    );
  }

  if (error && !claim) {
    return (
      <div className="mx-auto max-w-xl">
        <Alert variant="error" title="Could not load the claim">
          {error}
        </Alert>
        <Link href="/claims" className="btn-secondary mt-4">
          Back to claims
        </Link>
      </div>
    );
  }

  if (!claim) return null;

  // Decisions newest-first; the first one is the operative decision.
  const decisions = [...claim.decisions].sort(
    (a, b) => new Date(b.decided_at).getTime() - new Date(a.decided_at).getTime(),
  );
  const latest = decisions[0] ?? null;
  const summarySections = parseExecutiveSummary(latest?.executive_summary);
  const extracted = claim.extracted_fields;
  const charges = extracted?.itemised_charges
    ? Object.entries(extracted.itemised_charges)
    : [];

  return (
    <div className="space-y-6">
      {/* ── Header ──────────────────────────────────────────────── */}
      <div>
        <Link href="/claims" className="text-sm text-brand-600 hover:underline">
          ← Back to claims
        </Link>
        <div className="mt-2 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold">{claim.claim_item}</h1>
            <p className="mt-1 text-sm text-slate-500">
              {claim.patient_name} · {claim.medical_facility} ·{" "}
              {formatDate(claim.date_of_treatment)}
            </p>
          </div>
          <div className="text-right">
            <StatusBadge status={claim.status} />
            {claim.confidence_score !== null && (
              <p className="mt-1 text-sm text-slate-500">
                Confidence {formatConfidence(claim.confidence_score)}
              </p>
            )}
          </div>
        </div>
      </div>

      {inFlight && !pollExhausted && (
        <Alert variant="info" title="Assessment in progress">
          <p className="flex items-center gap-2">
            <Spinner label="Assessing" className="h-4 w-4" />
            The pipeline is reading the bill and checking it against the handbook.
            This page updates itself.
          </p>
        </Alert>
      )}

      {pollExhausted && (
        <Alert variant="warning" title="Still processing">
          This claim has been processing for longer than expected. Reload to check
          again, or ask an administrator to look at the pipeline logs.
        </Alert>
      )}

      {error && claim && (
        <Alert variant="warning" title="Could not refresh">
          {error}
        </Alert>
      )}

      {/* ── Executive summary ───────────────────────────────────── */}
      {summarySections.length > 0 && (
        <section className="card" aria-labelledby="summary-heading">
          <div className="card-header">
            <h2 id="summary-heading" className="card-title">
              Executive summary
            </h2>
          </div>
          <div className="space-y-4 px-5 py-4">
            {summarySections.map((section, index) => (
              <div key={`${section.heading ?? "section"}-${index}`}>
                {section.heading && (
                  <h3 className="text-sm font-semibold text-slate-900">
                    {section.heading}
                  </h3>
                )}
                <p className="mt-1 whitespace-pre-line text-sm text-slate-700">
                  {section.body}
                </p>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ── Decision reason + citations ──────────────────────────── */}
      {latest && (
        <section className="card" aria-labelledby="decision-heading">
          <div className="card-header flex flex-wrap items-center justify-between gap-2">
            <h2 id="decision-heading" className="card-title">
              Decision
            </h2>
            <p className="text-xs text-slate-500">
              {latest.model_name && <>Model {latest.model_name} · </>}
              {latest.prompt_version && <>Prompt {latest.prompt_version} · </>}
              {formatDateTime(latest.decided_at)}
            </p>
          </div>
          <div className="px-5 py-4">
            <div className="flex items-center gap-3">
              <StatusBadge status={latest.outcome} />
              {latest.confidence_score !== null && (
                <span className="text-sm text-slate-500">
                  Confidence {formatConfidence(latest.confidence_score)}
                </span>
              )}
            </div>
            {latest.reason && (
              <p className="mt-3 text-sm text-slate-700">{latest.reason}</p>
            )}

            <h3 className="mt-5 text-sm font-semibold text-slate-900">
              Handbook clauses applied
            </h3>
            {latest.cited_clauses && latest.cited_clauses.length > 0 ? (
              <ul className="mt-2 space-y-2">
                {latest.cited_clauses.map((clause, index) => {
                  const { heading, body } = normaliseClause(clause, index);
                  return (
                    <li
                      key={`${heading}-${index}`}
                      className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2"
                    >
                      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">
                        {heading}
                      </p>
                      <p className="mt-1 text-sm text-slate-700">{body}</p>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className="mt-2 text-sm text-slate-500">
                No clauses were cited. A decision reached without handbook evidence
                should be treated as unverified — this happens when a deterministic
                check (completeness, amount, consistency or exclusions) decided the
                claim before the policy check ran.
              </p>
            )}
          </div>
        </section>
      )}

      {/* ── Claim details ───────────────────────────────────────── */}
      <section className="card" aria-labelledby="claim-heading">
        <div className="card-header">
          <h2 id="claim-heading" className="card-title">
            Claim as submitted
          </h2>
        </div>
        <dl className="divide-y divide-slate-100 px-5 py-2">
          <DetailRow label="Patient">{claim.patient_name}</DetailRow>
          <DetailRow label="Reason / diagnosis">{claim.reason}</DetailRow>
          <DetailRow label="Facility">{claim.medical_facility}</DetailRow>
          <DetailRow label="Date of treatment">
            {formatDate(claim.date_of_treatment)}
          </DetailRow>
          <DetailRow label="Amount claimed">
            {formatCurrency(claim.claim_amount)}
          </DetailRow>
          <DetailRow label="Address">{claim.address}</DetailRow>
          {claim.description && (
            <DetailRow label="Description">{claim.description}</DetailRow>
          )}
          <DetailRow label="Submitted">{formatDateTime(claim.created_at)}</DetailRow>
          <DetailRow label="Bill">
            {claim.documents.length > 0 ? (
              <ul>
                {claim.documents.map((document) => (
                  <li key={document.id}>
                    {document.file_name}{" "}
                    <span className="text-slate-400">({document.mime_type})</span>
                  </li>
                ))}
              </ul>
            ) : (
              "—"
            )}
          </DetailRow>
        </dl>
      </section>

      {/* ── Extracted from the bill ──────────────────────────────── */}
      <section className="card" aria-labelledby="extracted-heading">
        <div className="card-header">
          <h2 id="extracted-heading" className="card-title">
            Read from the bill
          </h2>
        </div>
        {extracted ? (
          <>
            <dl className="divide-y divide-slate-100 px-5 py-2">
              <DetailRow label="Patient name">
                {extracted.patient_name_extracted ?? "—"}
              </DetailRow>
              <DetailRow label="Diagnosis">{extracted.diagnosis ?? "—"}</DetailRow>
              <DetailRow label="Facility">
                {extracted.facility_extracted ?? "—"}
              </DetailRow>
              <DetailRow label="Date">{formatDate(extracted.date_extracted)}</DetailRow>
              <DetailRow label="Bill total">
                {formatCurrency(extracted.total_amount_extracted)}
              </DetailRow>
              <DetailRow label="Extracted by">
                {extracted.llm_model ?? "—"}
                {extracted.prompt_version && (
                  <span className="text-slate-400"> · {extracted.prompt_version}</span>
                )}
              </DetailRow>
            </dl>

            {charges.length > 0 && (
              <div className="border-t border-slate-100 px-5 py-4">
                <h3 className="text-sm font-semibold text-slate-900">
                  Itemised charges
                </h3>
                <table className="mt-2 w-full text-sm">
                  <caption className="sr-only">
                    Line items read from the uploaded bill
                  </caption>
                  <thead className="text-left text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th scope="col" className="py-1 font-semibold">Item</th>
                      <th scope="col" className="py-1 text-right font-semibold">Amount</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {charges.map(([item, amount]) => (
                      <tr key={item}>
                        <td className="py-1.5 text-slate-700">{item}</td>
                        <td className="py-1.5 text-right tabular-nums text-slate-900">
                          {typeof amount === "number" || typeof amount === "string"
                            ? formatCurrency(amount)
                            : String(amount)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ) : (
          <p className="px-5 py-4 text-sm text-slate-500">
            {inFlight
              ? "The bill has not been read yet."
              : "Nothing was extracted from the bill."}
          </p>
        )}
      </section>

      {/* ── Timeline ────────────────────────────────────────────── */}
      {decisions.length > 0 && (
        <section className="card" aria-labelledby="timeline-heading">
          <div className="card-header">
            <h2 id="timeline-heading" className="card-title">
              Decision history
            </h2>
          </div>
          <ol className="divide-y divide-slate-100 px-5">
            {decisions.map((decision, index) => (
              <li key={decision.id} className="flex gap-4 py-4">
                <div className="flex flex-col items-center">
                  <span
                    aria-hidden="true"
                    className={`mt-1 h-2.5 w-2.5 rounded-full ${
                      index === 0 ? "bg-brand-500" : "bg-slate-300"
                    }`}
                  />
                  {index < decisions.length - 1 && (
                    <span aria-hidden="true" className="mt-1 w-px flex-1 bg-slate-200" />
                  )}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-2">
                    <StatusBadge status={decision.outcome} />
                    {index === 0 && (
                      <span className="text-xs font-medium uppercase tracking-wide text-brand-600">
                        current
                      </span>
                    )}
                    <span className="text-xs text-slate-500">
                      {formatDateTime(decision.decided_at)}
                    </span>
                  </div>
                  {decision.reason && (
                    <p className="mt-1 text-sm text-slate-600">{decision.reason}</p>
                  )}
                </div>
              </li>
            ))}
          </ol>
        </section>
      )}
    </div>
  );
}

export default function ClaimDetailPage() {
  const params = useParams<{ id: string }>();
  const claimId = Array.isArray(params.id) ? params.id[0] : params.id;

  return (
    <RouteGuard>
      {claimId ? (
        <ClaimDetail claimId={claimId} />
      ) : (
        <Alert variant="error">No claim id in the URL.</Alert>
      )}
    </RouteGuard>
  );
}
