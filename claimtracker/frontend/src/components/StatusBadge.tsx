/**
 * Status pill, used by the claims table, the detail header and the queue.
 *
 * Colour is never the only signal: each status also carries a distinct glyph
 * and its text, so the badge survives greyscale printing and colour-blindness.
 */
import type { ClaimStatus } from "@/lib/api/types";
import { humaniseStatus } from "@/lib/format";

const STYLES: Record<ClaimStatus, { classes: string; glyph: string }> = {
  PENDING: { classes: "bg-amber-50 text-status-pending ring-amber-200", glyph: "○" },
  PROCESSING: { classes: "bg-sky-50 text-status-processing ring-sky-200", glyph: "◐" },
  ACCEPTED: { classes: "bg-green-50 text-status-accepted ring-green-200", glyph: "✓" },
  REJECTED: { classes: "bg-red-50 text-status-rejected ring-red-200", glyph: "✕" },
  NEEDS_REVIEW: { classes: "bg-orange-50 text-status-review ring-orange-200", glyph: "⚠" },
};

export function StatusBadge({ status }: { status: ClaimStatus }) {
  const style = STYLES[status] ?? STYLES.PENDING;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style.classes}`}
    >
      <span aria-hidden="true">{style.glyph}</span>
      {humaniseStatus(status)}
    </span>
  );
}
