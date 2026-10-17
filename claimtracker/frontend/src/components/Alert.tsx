import type { ReactNode } from "react";

type Variant = "error" | "warning" | "info" | "success";

const VARIANTS: Record<Variant, { classes: string; glyph: string; label: string }> = {
  error: { classes: "border-red-300 bg-red-50 text-red-900", glyph: "✕", label: "Error" },
  warning: {
    classes: "border-amber-300 bg-amber-50 text-amber-900",
    glyph: "⚠",
    label: "Warning",
  },
  info: { classes: "border-sky-300 bg-sky-50 text-sky-900", glyph: "ℹ", label: "Note" },
  success: {
    classes: "border-green-300 bg-green-50 text-green-900",
    glyph: "✓",
    label: "Success",
  },
};

/**
 * Inline message block. Errors use role="alert" so screen readers announce
 * them as soon as they appear; the quieter variants use role="status".
 */
export function Alert({
  variant = "error",
  title,
  children,
}: {
  variant?: Variant;
  title?: string;
  children: ReactNode;
}) {
  const style = VARIANTS[variant];
  return (
    <div
      role={variant === "error" ? "alert" : "status"}
      className={`flex gap-3 rounded-lg border px-4 py-3 text-sm ${style.classes}`}
    >
      <span aria-hidden="true" className="mt-0.5 font-semibold">
        {style.glyph}
      </span>
      <div className="min-w-0">
        <p className="sr-only">{style.label}:</p>
        {title && <p className="font-semibold">{title}</p>}
        <div className={title ? "mt-0.5" : ""}>{children}</div>
      </div>
    </div>
  );
}
