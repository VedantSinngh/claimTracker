/**
 * src/lib/format.test.ts
 * ───────────────────────
 * The formatting layer carries real risk: the backend sends Decimals as JSON
 * strings and dates as bare YYYY-MM-DD, and both are easy to render wrongly
 * (NaN, or a date one day off). These tests pin that behaviour down.
 */
import {
  formatConfidence,
  formatCurrency,
  formatDate,
  formatFileSize,
  formatSeconds,
  humaniseStatus,
  normaliseClause,
  parseAmount,
  parseExecutiveSummary,
} from "./format";

describe("parseAmount", () => {
  it("parses the string form the backend sends for Decimal", () => {
    expect(parseAmount("9860.00")).toBe(9860);
  });

  it("passes numbers through", () => {
    expect(parseAmount(1234.56)).toBe(1234.56);
  });

  it("returns null rather than NaN for unusable input", () => {
    expect(parseAmount(null)).toBeNull();
    expect(parseAmount(undefined)).toBeNull();
    expect(parseAmount("")).toBeNull();
    expect(parseAmount("not a number")).toBeNull();
  });

  it("treats zero as a value, not as absent", () => {
    expect(parseAmount("0.00")).toBe(0);
  });
});

describe("formatCurrency", () => {
  it("formats a decimal string as USD", () => {
    expect(formatCurrency("9860.00")).toBe("$9,860.00");
  });

  it("always shows two decimal places", () => {
    expect(formatCurrency("1150")).toBe("$1,150.00");
  });

  it("shows a dash when there is no amount", () => {
    expect(formatCurrency(null)).toBe("—");
    expect(formatCurrency("garbage")).toBe("—");
  });
});

describe("formatDate", () => {
  it("does not shift the day across timezones", () => {
    // `new Date("2024-03-15")` parses as UTC midnight, which renders as the
    // 14th anywhere west of Greenwich. The output must stay the 15th.
    expect(formatDate("2024-03-15")).toBe("Mar 15, 2024");
  });

  it("accepts a full timestamp and uses only the date part", () => {
    expect(formatDate("2024-03-15T23:30:00Z")).toBe("Mar 15, 2024");
  });

  it("shows a dash when absent", () => {
    expect(formatDate(null)).toBe("—");
  });

  it("returns the raw value when it cannot be parsed", () => {
    expect(formatDate("not-a-date")).toBe("not-a-date");
  });
});

describe("formatConfidence", () => {
  it("renders a fraction as a percentage", () => {
    expect(formatConfidence(0.93)).toBe("93%");
    expect(formatConfidence(0.4)).toBe("40%");
  });

  it("distinguishes zero confidence from no confidence", () => {
    expect(formatConfidence(0)).toBe("0%");
    expect(formatConfidence(null)).toBe("—");
  });
});

describe("humaniseStatus", () => {
  it("turns the enum into a sentence-cased label", () => {
    expect(humaniseStatus("NEEDS_REVIEW")).toBe("Needs review");
    expect(humaniseStatus("ACCEPTED")).toBe("Accepted");
  });
});

describe("formatSeconds", () => {
  it("keeps short durations in seconds", () => {
    expect(formatSeconds("15.00")).toBe("15.0s");
  });

  it("switches to minutes past a minute", () => {
    expect(formatSeconds(100)).toBe("1.7 min");
  });

  it("shows a dash when absent", () => {
    expect(formatSeconds(null)).toBe("—");
  });
});

describe("normaliseClause", () => {
  it("uses the clause/text object the prompt asks for", () => {
    expect(
      normaliseClause({ clause: "SECTION 2.1", text: "Hospitalisation is covered." }, 0),
    ).toEqual({ heading: "SECTION 2.1", body: "Hospitalisation is covered." });
  });

  it("handles a bare string, which the LLM sometimes returns instead", () => {
    expect(normaliseClause("Section 4 applies.", 2)).toEqual({
      heading: "Clause 3",
      body: "Section 4 applies.",
    });
  });

  it("falls back to a numbered heading when the object has no clause", () => {
    expect(normaliseClause({ text: "Some text." }, 0)).toEqual({
      heading: "Clause 1",
      body: "Some text.",
    });
  });

  it("never renders an empty card for an unexpected shape", () => {
    const result = normaliseClause({ clause: "SECTION 9" }, 0);
    expect(result.heading).toBe("SECTION 9");
    expect(result.body).toContain("SECTION 9");
  });
});

describe("parseExecutiveSummary", () => {
  const summary = [
    "**Introduction**\nClaim for an emergency appendectomy.",
    "**Claim Details**\n- Amount: $9,860.00\n- Facility: Metropolitan General",
    "**Decision Reason**\nCovered under Section 2.1.",
  ].join("\n\n");

  it("splits the backend's bold-heading blocks into sections", () => {
    const sections = parseExecutiveSummary(summary);
    expect(sections).toHaveLength(3);
    expect(sections[0]).toEqual({
      heading: "Introduction",
      body: "Claim for an emergency appendectomy.",
    });
    expect(sections[1].heading).toBe("Claim Details");
    expect(sections[1].body).toContain("$9,860.00");
  });

  it("keeps multi-line bodies intact", () => {
    const sections = parseExecutiveSummary(summary);
    expect(sections[1].body.split("\n")).toHaveLength(2);
  });

  it("returns a single untitled section for plain text", () => {
    expect(parseExecutiveSummary("Just a sentence.")).toEqual([
      { heading: null, body: "Just a sentence." },
    ]);
  });

  it("returns nothing for an empty summary", () => {
    expect(parseExecutiveSummary(null)).toEqual([]);
    expect(parseExecutiveSummary("   ")).toEqual([]);
  });
});

describe("formatFileSize", () => {
  it("scales the unit to the size", () => {
    expect(formatFileSize(512)).toBe("512 B");
    expect(formatFileSize(2048)).toBe("2 KB");
    expect(formatFileSize(3 * 1024 * 1024)).toBe("3.0 MB");
  });
});
