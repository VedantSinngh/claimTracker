/** Indeterminate loading indicator. */
export function Spinner({
  label = "Loading",
  className = "h-5 w-5",
}: {
  label?: string;
  className?: string;
}) {
  return (
    <span role="status" className="inline-flex items-center gap-2">
      <svg
        className={`animate-spin text-brand-500 ${className}`}
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" opacity="0.25" />
        <path
          d="M22 12a10 10 0 0 0-10-10"
          stroke="currentColor"
          strokeWidth="3"
          strokeLinecap="round"
        />
      </svg>
      <span className="sr-only">{label}</span>
    </span>
  );
}
