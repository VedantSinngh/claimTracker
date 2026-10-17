"use client";

/**
 * src/app/admin/handbook/page.tsx
 * ────────────────────────────────
 * Handbook ingestion. Admin only.
 *
 * Unlike claim submission, ingestion is **synchronous** on the backend: the
 * request does not return until the PDF has been chunked, every chunk
 * embedded, the FAISS index written and the exclusions seeded. On a large
 * handbook that is tens of seconds, and the first ever upload also downloads
 * the sentence-transformers model. The UI therefore warns before and keeps the
 * button disabled throughout, rather than letting someone think it hung.
 */
import { useCallback, useEffect, useRef, useState } from "react";

import { Alert } from "@/components/Alert";
import { EmptyState } from "@/components/EmptyState";
import { RouteGuard } from "@/components/RouteGuard";
import { Spinner } from "@/components/Spinner";
import { ApiError, handbooksApi } from "@/lib/api/client";
import type { HandbookResponse } from "@/lib/api/types";
import { formatDateTime, formatFileSize } from "@/lib/format";

const MAX_SIZE_MB = 20;

function HandbookAdmin() {
  const [versions, setVersions] = useState<HandbookResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [versionTag, setVersionTag] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  // The file input is uncontrolled, so clearing it after a successful upload
  // needs the DOM node.
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const result = await handbooksApi.list();
      // Newest first.
      setVersions(
        [...result.items].sort(
          (a, b) =>
            new Date(b.uploaded_at).getTime() - new Date(a.uploaded_at).getTime(),
        ),
      );
      setLoadError(null);
    } catch (cause) {
      setLoadError(
        cause instanceof ApiError ? cause.detail : "Could not load handbook versions.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function handleUpload(event: React.FormEvent) {
    event.preventDefault();
    setUploadError(null);
    setSuccess(null);

    if (!versionTag.trim()) {
      setUploadError("Give the version a tag, e.g. 2024-01.");
      return;
    }
    if (!file) {
      setUploadError("Choose the handbook PDF.");
      return;
    }
    if (file.type !== "application/pdf") {
      setUploadError("The handbook must be a PDF.");
      return;
    }
    if (file.size > MAX_SIZE_MB * 1024 * 1024) {
      setUploadError(`The handbook must be under ${MAX_SIZE_MB} MB.`);
      return;
    }

    setUploading(true);
    try {
      const created = await handbooksApi.upload(versionTag.trim(), file);
      setSuccess(
        `Ingested “${created.version_tag}” — ${created.chunk_count ?? 0} chunks indexed. ` +
          "It is now the active handbook.",
      );
      setVersionTag("");
      setFile(null);
      if (fileInputRef.current) fileInputRef.current.value = "";
      await load();
    } catch (cause) {
      setUploadError(
        cause instanceof ApiError
          ? cause.detail
          : "Could not ingest the handbook. Check the backend logs.",
      );
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-semibold">Policy handbook</h1>
        <p className="mt-1 text-sm text-slate-500">
          Uploading a handbook chunks it (1000 characters, 200 overlap), embeds every
          chunk, rebuilds the FAISS index, seeds the exclusions list from the
          General Exclusions section, and makes this version active.
        </p>
      </div>

      <section className="card" aria-labelledby="upload-heading">
        <div className="card-header">
          <h2 id="upload-heading" className="card-title">
            Upload a new version
          </h2>
        </div>
        <form onSubmit={handleUpload} className="space-y-4 px-5 py-4" noValidate>
          {uploadError && (
            <Alert variant="error" title="Ingestion failed">
              {uploadError}
            </Alert>
          )}
          {success && <Alert variant="success">{success}</Alert>}

          <div className="sm:max-w-xs">
            <label htmlFor="version_tag" className="field-label">
              Version tag
            </label>
            <input
              id="version_tag"
              name="version_tag"
              type="text"
              required
              className="field-input"
              placeholder="2024-01"
              value={versionTag}
              onChange={(event) => setVersionTag(event.target.value)}
              disabled={uploading}
            />
          </div>

          <div>
            <label htmlFor="handbook_file" className="field-label">
              Handbook PDF
            </label>
            <input
              id="handbook_file"
              name="handbook_file"
              ref={fileInputRef}
              type="file"
              accept=".pdf"
              required
              disabled={uploading}
              aria-describedby="handbook-hint"
              className="block w-full rounded-md border border-slate-300 px-3 py-2 text-sm
                         file:mr-3 file:rounded file:border-0 file:bg-brand-50
                         file:px-3 file:py-1.5 file:text-sm file:font-medium
                         file:text-brand-700 hover:file:bg-brand-100"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            <p id="handbook-hint" className="mt-1 text-xs text-slate-500">
              Must be a digital PDF — a pure scan has no extractable text and will be
              rejected. Up to {MAX_SIZE_MB} MB.
              {file && ` Selected: ${file.name} (${formatFileSize(file.size)}).`}
            </p>
          </div>

          <Alert variant="info">
            Ingestion runs synchronously and can take up to a minute. The very first
            upload also downloads the embedding model. Keep this tab open.
          </Alert>

          <button type="submit" className="btn-primary" disabled={uploading}>
            {uploading ? <Spinner label="Ingesting the handbook" /> : "Ingest handbook"}
          </button>
          {uploading && (
            <p className="text-sm text-slate-500">
              Chunking, embedding and indexing…
            </p>
          )}
        </form>
      </section>

      <section aria-labelledby="versions-heading">
        <h2 id="versions-heading" className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          Versions
        </h2>

        {loadError && (
          <div className="mt-3">
            <Alert variant="error">{loadError}</Alert>
          </div>
        )}

        {loading && (
          <div className="mt-6 flex justify-center">
            <Spinner label="Loading versions" className="h-6 w-6" />
          </div>
        )}

        {!loading && versions.length === 0 && (
          <div className="mt-3">
            <EmptyState
              title="No handbook ingested yet"
              description="Until one is, the RAG policy check cannot run and claims will route to review."
            />
          </div>
        )}

        {!loading && versions.length > 0 && (
          <div className="card mt-3 overflow-x-auto">
            <table className="w-full min-w-[32rem] text-sm">
              <caption className="sr-only">Ingested handbook versions</caption>
              <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th scope="col" className="px-4 py-3 font-semibold">Version</th>
                  <th scope="col" className="px-4 py-3 text-right font-semibold">Chunks</th>
                  <th scope="col" className="px-4 py-3 font-semibold">Uploaded</th>
                  <th scope="col" className="px-4 py-3 font-semibold">Active</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {versions.map((version) => (
                  <tr key={version.id}>
                    <td className="px-4 py-3 font-medium text-slate-900">
                      {version.version_tag}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-slate-600">
                      {version.chunk_count ?? "—"}
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {formatDateTime(version.uploaded_at)}
                    </td>
                    <td className="px-4 py-3">
                      {version.is_active ? (
                        <span className="inline-flex items-center gap-1.5 rounded-full bg-green-50 px-2.5 py-0.5 text-xs font-medium text-status-accepted ring-1 ring-inset ring-green-200">
                          <span aria-hidden="true">✓</span> Active
                        </span>
                      ) : (
                        <span className="text-xs text-slate-400">Superseded</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

export default function HandbookPage() {
  return (
    <RouteGuard roles={["admin"]}>
      <HandbookAdmin />
    </RouteGuard>
  );
}
