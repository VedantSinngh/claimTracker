/**
 * src/lib/format.ts
 * ──────────────────
 * Display helpers. Kept separate from the API layer so they can be unit
 * tested without touching fetch.
 */
import type { CitedClause, ClaimStatus } from "@/lib/api/types";

/**
 * The backend serialises `Decimal` as a JSON string ("9860.00"), so amounts
 * must be parsed before any arithmetic or formatting. Returns null for
 * anything unparseable rather than NaN, so callers can show a dash.
 */
export function parseAmount(value: string | number | null | undefined): number | null {
  if (value === null || value === undefined || value === "") return null;
  const parsed = typeof value === "number" ? value : Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

export function formatCurrency(value: string | number | null | undefined): string {
  const parsed = parseAmount(value);
  if (parsed === null) return "—";
  return parsed.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/** A plain YYYY-MM-DD date — rendered without a timezone shift. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  // Splitting avoids `new Date("2024-03-15")` being read as UTC midnight and
  // displaying as the 14th for anyone west of Greenwich.
  const [year, month, day] = value.slice(0, 10).split("-").map(Number);
  if (!year || !month || !day) return value;
  return new Date(year, month - 1, day).toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

/** A timestamp, shown in the viewer's local zone. */
export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function formatConfidence(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(0)}%`;
}

/** "NEEDS_REVIEW" → "Needs review" */
export function humaniseStatus(status: ClaimStatus): string {
  const word = status.replace(/_/g, " ").toLowerCase();
  return word.charAt(0).toUpperCase() + word.slice(1);
}

export function formatSeconds(value: string | number | null | undefined): string {
  const parsed = parseAmount(value);
  if (parsed === null) return "—";
  if (parsed < 60) return `${parsed.toFixed(1)}s`;
  return `${(parsed / 60).toFixed(1)} min`;
}

/**
 * Normalises a cited clause into a heading and a body.
 *
 * `cited_clauses` is `List[Any]` on the backend and filled by the LLM, so an
 * element may be the `{clause, text}` object the prompt asks for, a bare
 * string, or an object with unexpected keys. Everything is coerced to
 * something renderable — a decision must always be able to show its evidence.
 */
export function normaliseClause(
  clause: CitedClause,
  index: number,
): { heading: string; body: string } {
  if (typeof clause === "string") {
    return { heading: `Clause ${index + 1}`, body: clause };
  }
  if (clause && typeof clause === "object") {
    const heading = clause.clause?.trim() || `Clause ${index + 1}`;
    const body = clause.text?.trim() || "";
    if (body) return { heading, body };
    // Unexpected shape: show the raw JSON rather than an empty card.
    return { heading, body: JSON.stringify(clause) };
  }
  return { heading: `Clause ${index + 1}`, body: String(clause) };
}

/**
 * Splits the backend's executive summary into sections.
 *
 * `DecisionService` joins `**Heading**\nbody` blocks with blank lines, so this
 * parses that back out for styled rendering. Anything that does not match the
 * pattern is returned as a single untitled section, so a plain-text summary
 * still displays.
 */
export function parseExecutiveSummary(
  summary: string | null | undefined,
): Array<{ heading: string | null; body: string }> {
  if (!summary?.trim()) return [];

  const blocks = summary.split(/\n{2,}/).filter((block) => block.trim());
  const sections: Array<{ heading: string | null; body: string }> = [];

  for (const block of blocks) {
    const match = block.match(/^\*\*(.+?)\*\*\s*\n?([\s\S]*)$/);
    if (match) {
      sections.push({ heading: match[1].trim(), body: match[2].trim() });
    } else {
      sections.push({ heading: null, body: block.trim() });
    }
  }
  return sections;
}

/** Bytes → "1.4 MB", for the upload field's hint text. */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
