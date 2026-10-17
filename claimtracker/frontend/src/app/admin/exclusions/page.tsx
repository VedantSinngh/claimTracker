"use client";

/**
 * src/app/admin/exclusions/page.tsx
 * ──────────────────────────────────
 * The exclusions list that `ExclusionCheckValidator` matches against. Admin only.
 *
 * This is the one place a human can correct the deterministic safety net, so
 * it matters that the consequences are visible: these terms are checked
 * *before* the LLM, and a bad term rejects real claims. Deleting is
 * destructive and irreversible, so it is behind an inline confirm rather than
 * a bare button — and `window.confirm` is deliberately avoided, since a native
 * modal blocks the page.
 */
import { useCallback, useEffect, useState } from "react";

import { Alert } from "@/components/Alert";
import { EmptyState } from "@/components/EmptyState";
import { RouteGuard } from "@/components/RouteGuard";
import { Spinner } from "@/components/Spinner";
import { ApiError, exclusionsApi } from "@/lib/api/client";
import type { ExclusionResponse } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";

const PAGE_SIZE = 100;

function ExclusionsAdmin() {
  const [items, setItems] = useState<ExclusionResponse[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [term, setTerm] = useState("");
  const [description, setDescription] = useState("");
  const [creating, setCreating] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await exclusionsApi.list({ skip: 0, limit: PAGE_SIZE });
      setItems(result.items);
      setTotal(result.total);
      setLoadError(null);
    } catch (cause) {
      setLoadError(
        cause instanceof ApiError ? cause.detail : "Could not load the exclusions list.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleCreate(event: React.FormEvent) {
    event.preventDefault();
    setFormError(null);
    setNotice(null);

    const trimmed = term.trim();
    if (trimmed.length < 2) {
      setFormError("Enter the excluded condition or treatment.");
      return;
    }
    if (items.some((item) => item.term.toLowerCase() === trimmed.toLowerCase())) {
      setFormError(`“${trimmed}” is already on the list.`);
      return;
    }

    setCreating(true);
    try {
      await exclusionsApi.create({
        term: trimmed,
        description: description.trim() || undefined,
      });
      setTerm("");
      setDescription("");
      setNotice(`Added “${trimmed}”.`);
      await load();
    } catch (cause) {
      setFormError(
        cause instanceof ApiError ? cause.detail : "Could not add the exclusion.",
      );
    } finally {
      setCreating(false);
    }
  }

  async function handleDelete(item: ExclusionResponse) {
    setNotice(null);
    setDeletingId(item.id);
    try {
      await exclusionsApi.remove(item.id);
      setConfirmingId(null);
      setNotice(`Removed “${item.term}”.`);
      await load();
    } catch (cause) {
      setLoadError(
        cause instanceof ApiError ? cause.detail : "Could not remove the exclusion.",
      );
    } finally {
      setDeletingId(null);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Exclusions</h1>
        <p className="mt-1 text-sm text-slate-500">
          Conditions and treatments the policy does not cover. These are matched
          deterministically — with fuzzy and synonym matching — <strong>before</strong>{" "}
          the claim ever reaches the model, so a term here rejects claims outright.
        </p>
      </div>

      <Alert variant="warning" title="Terms are seeded from the handbook">
        Ingesting a handbook adds the terms it finds under “General Exclusions”.
        Edit them here when the parser gets one wrong — a term that is too broad
        will reject legitimate claims.
      </Alert>

      <section className="card" aria-labelledby="add-heading">
        <div className="card-header">
          <h2 id="add-heading" className="card-title">
            Add an exclusion
          </h2>
        </div>
        <form onSubmit={handleCreate} className="space-y-4 px-5 py-4" noValidate>
          {formError && <Alert variant="error">{formError}</Alert>}

          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label htmlFor="term" className="field-label">
                Term
              </label>
              <input
                id="term"
                name="term"
                type="text"
                required
                minLength={2}
                maxLength={255}
                className="field-input"
                placeholder="e.g. cosmetic surgery"
                value={term}
                onChange={(event) => setTerm(event.target.value)}
                disabled={creating}
              />
            </div>
            <div>
              <label htmlFor="description" className="field-label">
                Note <span className="font-normal text-slate-400">(optional)</span>
              </label>
              <input
                id="description"
                name="description"
                type="text"
                className="field-input"
                placeholder="Why, or which clause it comes from"
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                disabled={creating}
              />
            </div>
          </div>

          <button type="submit" className="btn-primary" disabled={creating}>
            {creating ? <Spinner label="Adding exclusion" /> : "Add exclusion"}
          </button>
        </form>
      </section>

      <section aria-labelledby="list-heading">
        <div className="flex items-center justify-between">
          <h2
            id="list-heading"
            className="text-sm font-semibold uppercase tracking-wide text-slate-500"
          >
            Current list
          </h2>
          <p className="text-sm text-slate-500">
            {total} term{total === 1 ? "" : "s"}
            {total > PAGE_SIZE && ` (showing first ${PAGE_SIZE})`}
          </p>
        </div>

        {notice && (
          <div className="mt-3">
            <Alert variant="success">{notice}</Alert>
          </div>
        )}
        {loadError && (
          <div className="mt-3">
            <Alert variant="error">{loadError}</Alert>
          </div>
        )}

        {loading && (
          <div className="mt-6 flex justify-center">
            <Spinner label="Loading exclusions" className="h-6 w-6" />
          </div>
        )}

        {!loading && items.length === 0 && (
          <div className="mt-3">
            <EmptyState
              title="No exclusions"
              description="Every diagnosis will pass the exclusion check until a term is added or a handbook is ingested."
            />
          </div>
        )}

        {!loading && items.length > 0 && (
          <ul className="card mt-3 divide-y divide-slate-100">
            {items.map((item) => (
              <li key={item.id} className="px-5 py-3">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <p className="font-medium text-slate-900">{item.term}</p>
                    {item.description && (
                      <p className="mt-0.5 text-sm text-slate-500">{item.description}</p>
                    )}
                    <p className="mt-0.5 text-xs text-slate-400">
                      Added {formatDateTime(item.created_at)}
                      {!item.is_active && " · inactive"}
                    </p>
                  </div>

                  {confirmingId === item.id ? (
                    <div className="flex items-center gap-2">
                      <span className="text-sm text-slate-600">Remove this term?</span>
                      <button
                        type="button"
                        className="btn-danger"
                        disabled={deletingId === item.id}
                        onClick={() => void handleDelete(item)}
                      >
                        {deletingId === item.id ? (
                          <Spinner label="Removing" className="h-4 w-4" />
                        ) : (
                          "Remove"
                        )}
                      </button>
                      <button
                        type="button"
                        className="btn-secondary"
                        disabled={deletingId === item.id}
                        onClick={() => setConfirmingId(null)}
                      >
                        Keep
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => setConfirmingId(item.id)}
                    >
                      Remove
                      <span className="sr-only"> {item.term}</span>
                    </button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

export default function ExclusionsPage() {
  return (
    <RouteGuard roles={["admin"]}>
      <ExclusionsAdmin />
    </RouteGuard>
  );
}
