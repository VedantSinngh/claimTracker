import Link from "next/link";

export default function NotFound() {
  return (
    <div className="mx-auto max-w-md py-16 text-center">
      <p className="text-sm font-semibold uppercase tracking-wide text-slate-400">404</p>
      <h1 className="mt-2 text-2xl font-semibold">Page not found</h1>
      <p className="mt-2 text-sm text-slate-500">
        That page does not exist. If you followed a link to a claim, it may have been
        removed, or it may belong to another account.
      </p>
      <Link href="/claims" className="btn-primary mt-6">
        Go to claims
      </Link>
    </div>
  );
}
