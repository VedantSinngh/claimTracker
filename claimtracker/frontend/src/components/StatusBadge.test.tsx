/**
 * src/components/StatusBadge.test.tsx
 * ────────────────────────────────────
 * The badge is how status is communicated across every page, so the thing
 * worth testing is that it never relies on colour alone — colour-blind and
 * greyscale users must still be able to read the status.
 */
import { render, screen } from "@testing-library/react";

import { CLAIM_STATUSES } from "@/lib/api/types";

import { StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it.each(CLAIM_STATUSES)("renders a readable label for %s", (status) => {
    render(<StatusBadge status={status} />);
    const expected = status.charAt(0) + status.slice(1).toLowerCase().replace(/_/g, " ");
    expect(screen.getByText(expected)).toBeInTheDocument();
  });

  it("gives every status its own glyph, so colour is never the only signal", () => {
    const glyphs = CLAIM_STATUSES.map((status) => {
      const { container, unmount } = render(<StatusBadge status={status} />);
      const glyph = container.querySelector('[aria-hidden="true"]')?.textContent ?? "";
      unmount();
      return glyph;
    });

    expect(glyphs.every((glyph) => glyph.length > 0)).toBe(true);
    expect(new Set(glyphs).size).toBe(CLAIM_STATUSES.length);
  });

  it("hides the decorative glyph from assistive tech", () => {
    const { container } = render(<StatusBadge status="ACCEPTED" />);
    expect(container.querySelector('[aria-hidden="true"]')).toBeInTheDocument();
  });

  it("falls back to a valid style for an unrecognised status", () => {
    // The API types this as a union, but a new backend status should degrade
    // to a rendered badge rather than a blank one.
    // @ts-expect-error — deliberately outside the union
    render(<StatusBadge status="SOMETHING_NEW" />);
    expect(screen.getByText("Something new")).toBeInTheDocument();
  });
});
