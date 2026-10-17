"use client";

/**
 * src/app/claims/page.tsx
 * ────────────────────────
 * The claims list. A plain user sees their own; reviewers and admins see all
 * (the backend decides that from the token, so there is nothing to pass).
 *
 * Any claim still in PENDING or PROCESSING means the background pipeline is
 * running, so the list polls until nothing is in flight. The poll stops as
 * soon as every row is terminal, rather than running forever.
 */
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { Alert } from "@/components/Alert";
import { EmptyState } from "@/components/EmptyState";
import { Spinner } from "@/components/Spinner";
import { StatusBadge } from "@/components/StatusBadge";
import { RouteGuard } from "@/components/RouteGuard";
import { ApiError, claimsApi } from "@/lib/api/client";
import {
  CLAIM_STATUSES,
  IN_FLIGHT_STATUSES,
  type ClaimListResponse,
  type ClaimStatus,
} from "@/lib/api/types";
import { formatCurrency, formatDate, humaniseStatus } from "@/lib/format";

const PAGE_SIZE = 20;
const POLL_INTERVAL_MS = 4000;

function ClaimsTable() {
  const [data, setData] = useState<ClaimListResponse | null>(null);
  const [status, setStatus] = useState<ClaimStatus | "">("");
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Kept in a ref so the poll effect does not re-subscribe on every refresh.
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(
    async (options: { silent?: boolean } = {}) => {
      if (!options.silent) setLoading(true);
      try {
        const result = await claimsApi.list({ status, page, pageSize: PAGE_SIZE });
        setData(result);
        setError(null);
      } catch (cause) {
        // A failed background refresh should not wipe the table that is
        // already on screen; only surface it if we have nothing to show.
        if (cause instanceof ApiError) {
          if (!options.silent || data === null) setError(cause.detail);
        } else if (!options.silent) {
          setError("Could not load your claims.");
        }
      } finally {
        if (!options.silent) setLoading(false);
      }
    },
    // `data` is read only to decide whether to surface a silent error.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [status, page],
  );

  useEffect(() => {
    void load();
  }, [load]);

  // Poll only while something is actually in flight.
  const hasInFlight = Boolean(
    data?.items.some((claim) => IN_FLIGHT_STATUSES.includes(claim.status)),
  );

  useEffect(() => {
    if (!hasInFlight) {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
      return;
    }
    pollRef.current = setInterval(() => void load({ silent: true }), POLL_INTERVAL_MS);
    return () => {
      if (pollRef.current) clearInterval(pollRef.current);
      pollRef.current = null;
    };
  }, [hasInFlight, load]);

  const totalPages = data ? Math.max(1, Math.ceil(data.total / data.page_size)) : 1;

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold">Claims</h1>
          <p className="mt-1 text-sm text-slate-500">
            {data ? `${data.total} total` : "Loading…"}
            {hasInFlight && (
              <span className="ml-2 text-brand-600">· refreshing while processing</span>
            )}
          </p>
        </div>

        <div className="flex items-end gap-3">
          <div>
            <label htmlFor="status-filter" className="field-label">
              Status
            </label>
            <select
              id="status-filter"
              className="field-input"
              value={status}
              onChange={(event) => {
                setStatus(event.target.value as ClaimStatus | "");
                setPage(1);
              }}
            >
              <option value="">All statuses</option>
              {CLAIM_STATUSES.map((option) => (
                <option key={option} value={option}>
                  {humaniseStatus(option)}
                </option>
              ))}
            </select>
          </div>
          <Link href="/claims/new" className="btn-primary">
            Submit a claim
          </Link>
        </div>
      </div>

      {error && (
        <div className="mt-6">
          <Alert variant="error" title="Could not load claims">
            {error}
          </Alert>
        </div>
      )}

      {loading && !data && (
        <div className="mt-10 flex justify-center">
          <Spinner label="Loading claims" className="h-8 w-8" />
        </div>
      )}

      {data && data.items.length === 0 && (
        <div className="mt-6">
          <EmptyState
            title={status ? `No ${humaniseStatus(status).toLowerCase()} claims` : "No claims yet"}
            description={
              status
                ? "Try a different status filter."
                : "Submit a bill and the pipeline will assess it in seconds."
            }
            action={
              status ? (
                <button type="button" className="btn-secondary" onClick={() => setStatus("")}>
                  Clear filter
                </button>
              ) : (
                <Link href="/claims/new" className="btn-primary">
                  Submit a claim
                </Link>
              )
            }
          />
        </div>
      )}

      {data && data.items.length > 0 && (
        <>
          <div className="card mt-6 overflow-x-auto">
            <table className="w-full min-w-[46rem] text-sm">
              <caption className="sr-only">
                Claims, newest first. Each row links to the full decision.
              </caption>
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th scope="col" className="px-4 py-3 font-semibold">Patient</th>
                  <th scope="col" className="px-4 py-3 font-semibold">Item</th>
                  <th scope="col" className="px-4 py-3 font-semibold">Facility</th>
                  <th scope="col" className="px-4 py-3 font-semibold">Treated</th>
                  <th scope="col" className="px-4 py-3 text-right font-semibold">Amount</th>
                  <th scope="col" className="px-4 py-3 font-semibold">Status</th>
                  <th scope="col" className="px-4 py-3 font-semibold">
                    <span className="sr-only">Actions</span>
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.items.map((claim) => (
                  <tr key={claim.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 font-medium text-slate-900">
                      {claim.patient_name}
                    </td>
                    <td className="px-4 py-3 text-slate-600">{claim.claim_item}</td>
                    <td className="px-4 py-3 text-slate-600">{claim.medical_facility}</td>
                    <td className="px-4 py-3 text-slate-600">
                      {formatDate(claim.date_of_treatment)}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-slate-900">
                      {formatCurrency(claim.claim_amount)}
                    </td>
                    <td className="px-4 py-3">
                      <StatusBadge status={claim.status} />
                    </td>
                    <td className="px-4 py-3 text-right">
                      <Link
                        href={`/claims/${claim.id}`}
                        className="font-medium text-brand-600 hover:underline"
                      >
                        View
                        <span className="sr-only"> claim for {claim.patient_name}</span>
                      </Link>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <nav
              aria-label="Pagination"
              className="mt-4 flex items-center justify-between text-sm"
            >
              <button
                type="button"
                className="btn-secondary"
                disabled={page <= 1}
                onClick={() => setPage((current) => Math.max(1, current - 1))}
              >
                Previous
              </button>
              <span className="text-slate-600">
                Page {data.page} of {totalPages}
              </span>
              <button
                type="button"
                className="btn-secondary"
                disabled={page >= totalPages}
                onClick={() => setPage((current) => current + 1)}
              >
                Next
              </button>
            </nav>
          )}
        </>
      )}
    </>
  );
}

export default function ClaimsPage() {
  return (
    <RouteGuard>
      <ClaimsTable />
    </RouteGuard>
  );
}
