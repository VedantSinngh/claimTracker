"use client";

/**
 * src/app/claims/new/page.tsx
 * ────────────────────────────
 * The claim submission form.
 *
 * The file constraints mirror `ClaimService.submit_claim`: PDF/JPG/PNG only,
 * and MAX_UPLOAD_SIZE_MB (20 by default). They are checked here so the user
 * is not made to upload 30MB before being told no — the server still rejects
 * independently, which is what actually matters.
 *
 * On success the backend returns a PENDING claim and runs the pipeline in the
 * background, so we navigate straight to the detail page, which polls.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/Alert";
import { RouteGuard } from "@/components/RouteGuard";
import { Spinner } from "@/components/Spinner";
import { ApiError, claimsApi } from "@/lib/api/client";
import { useAuth } from "@/lib/auth/AuthProvider";
import { formatFileSize } from "@/lib/format";

const ACCEPTED_TYPES = ["application/pdf", "image/jpeg", "image/png"];
const ACCEPT_ATTR = ".pdf,.jpg,.jpeg,.png";
const MAX_SIZE_MB = 20;

interface FormState {
  patient_name: string;
  claim_item: string;
  reason: string;
  address: string;
  date_of_treatment: string;
  medical_facility: string;
  claim_amount: string;
  description: string;
}

const EMPTY_FORM: FormState = {
  patient_name: "",
  claim_item: "",
  reason: "",
  address: "",
  date_of_treatment: "",
  medical_facility: "",
  claim_amount: "",
  description: "",
};

/** Client-side mirror of the backend's field constraints. */
function validate(form: FormState, file: File | null): Record<string, string> {
  const errors: Record<string, string> = {};

  if (form.patient_name.trim().length < 2) {
    errors.patient_name = "Enter the patient's full name.";
  }
  if (form.claim_item.trim().length < 2) {
    errors.claim_item = "What is being claimed for?";
  }
  if (form.reason.trim().length < 2) {
    errors.reason = "Give the diagnosis or reason for treatment.";
  }
  if (form.address.trim().length < 5) {
    errors.address = "Enter the patient's address.";
  }
  if (!form.date_of_treatment) {
    errors.date_of_treatment = "Select the date of treatment.";
  } else if (form.date_of_treatment > new Date().toISOString().slice(0, 10)) {
    errors.date_of_treatment = "The date of treatment cannot be in the future.";
  }
  if (form.medical_facility.trim().length < 2) {
    errors.medical_facility = "Enter the hospital or clinic name.";
  }

  const amount = Number(form.claim_amount);
  if (!form.claim_amount || !Number.isFinite(amount) || amount <= 0) {
    errors.claim_amount = "Enter the amount being claimed.";
  }

  if (!file) {
    errors.bill_file = "Attach the itemised bill.";
  } else if (!ACCEPTED_TYPES.includes(file.type)) {
    errors.bill_file = "The bill must be a PDF, JPG or PNG.";
  } else if (file.size > MAX_SIZE_MB * 1024 * 1024) {
    errors.bill_file = `The bill must be under ${MAX_SIZE_MB} MB (yours is ${formatFileSize(file.size)}).`;
  }

  return errors;
}

function SubmitClaimForm() {
  const router = useRouter();
  const { user } = useAuth();

  const [form, setForm] = useState<FormState>({
    ...EMPTY_FORM,
    // Most claims are filed for the account holder; pre-fill but keep editable.
    patient_name: user?.full_name ?? "",
  });
  const [file, setFile] = useState<File | null>(null);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  function update<K extends keyof FormState>(key: K, value: string) {
    setForm((current) => ({ ...current, [key]: value }));
    // Clear the field's error as soon as the user edits it.
    setErrors((current) => {
      if (!current[key]) return current;
      const next = { ...current };
      delete next[key];
      return next;
    });
  }

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    setSubmitError(null);

    const validationErrors = validate(form, file);
    if (Object.keys(validationErrors).length > 0) {
      setErrors(validationErrors);
      return;
    }
    setErrors({});
    setSubmitting(true);

    try {
      const claim = await claimsApi.submit(
        {
          patient_name: form.patient_name.trim(),
          claim_item: form.claim_item.trim(),
          reason: form.reason.trim(),
          address: form.address.trim(),
          date_of_treatment: form.date_of_treatment,
          medical_facility: form.medical_facility.trim(),
          claim_amount: Number(form.claim_amount),
          description: form.description.trim() || undefined,
        },
        file as File,
      );
      router.push(`/claims/${claim.id}`);
    } catch (cause) {
      if (cause instanceof ApiError) {
        if (cause.fieldErrors.length > 0) {
          setErrors(
            Object.fromEntries(cause.fieldErrors.map((item) => [item.field, item.message])),
          );
        }
        setSubmitError(cause.detail);
      } else {
        setSubmitError("Could not submit the claim. Please try again.");
      }
      setSubmitting(false);
    }
    // On success we navigate away, so `submitting` stays true deliberately —
    // it keeps the button disabled and prevents a double submit.
  }

  function fieldProps(key: keyof FormState) {
    return {
      id: key,
      name: key,
      value: form[key],
      disabled: submitting,
      "aria-invalid": Boolean(errors[key]),
      "aria-describedby": errors[key] ? `${key}-error` : undefined,
      onChange: (
        event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>,
      ) => update(key, event.target.value),
    };
  }

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-2xl font-semibold">Submit a claim</h1>
      <p className="mt-1 text-sm text-slate-500">
        Attach the itemised bill. The assessment usually finishes in seconds.
      </p>

      <form onSubmit={handleSubmit} className="mt-6 space-y-5" noValidate>
        {submitError && (
          <Alert variant="error" title="Could not submit the claim">
            {submitError}
          </Alert>
        )}

        <div className="grid gap-5 sm:grid-cols-2">
          <div className="sm:col-span-2">
            <label htmlFor="patient_name" className="field-label">
              Patient name
            </label>
            <input type="text" className="field-input" required {...fieldProps("patient_name")} />
            {errors.patient_name && (
              <p id="patient_name-error" className="field-error">
                {errors.patient_name}
              </p>
            )}
          </div>

          <div>
            <label htmlFor="claim_item" className="field-label">
              Claim item
            </label>
            <input
              type="text"
              className="field-input"
              placeholder="e.g. Hospitalisation"
              required
              {...fieldProps("claim_item")}
            />
            {errors.claim_item && (
              <p id="claim_item-error" className="field-error">
                {errors.claim_item}
              </p>
            )}
          </div>

          <div>
            <label htmlFor="reason" className="field-label">
              Reason / diagnosis
            </label>
            <input
              type="text"
              className="field-input"
              placeholder="e.g. Acute appendicitis"
              required
              {...fieldProps("reason")}
            />
            {errors.reason && (
              <p id="reason-error" className="field-error">
                {errors.reason}
              </p>
            )}
          </div>

          <div>
            <label htmlFor="medical_facility" className="field-label">
              Medical facility
            </label>
            <input
              type="text"
              className="field-input"
              required
              {...fieldProps("medical_facility")}
            />
            {errors.medical_facility && (
              <p id="medical_facility-error" className="field-error">
                {errors.medical_facility}
              </p>
            )}
          </div>

          <div>
            <label htmlFor="date_of_treatment" className="field-label">
              Date of treatment
            </label>
            <input
              type="date"
              className="field-input"
              required
              max={new Date().toISOString().slice(0, 10)}
              {...fieldProps("date_of_treatment")}
            />
            {errors.date_of_treatment && (
              <p id="date_of_treatment-error" className="field-error">
                {errors.date_of_treatment}
              </p>
            )}
          </div>

          <div className="sm:col-span-2">
            <label htmlFor="address" className="field-label">
              Patient address
            </label>
            <input type="text" className="field-input" required {...fieldProps("address")} />
            {errors.address && (
              <p id="address-error" className="field-error">
                {errors.address}
              </p>
            )}
          </div>

          <div>
            <label htmlFor="claim_amount" className="field-label">
              Amount claimed (USD)
            </label>
            <input
              type="number"
              min="0.01"
              step="0.01"
              inputMode="decimal"
              className="field-input"
              required
              {...fieldProps("claim_amount")}
            />
            {errors.claim_amount && (
              <p id="claim_amount-error" className="field-error">
                {errors.claim_amount}
              </p>
            )}
          </div>

          <div className="sm:col-span-2">
            <label htmlFor="description" className="field-label">
              Description <span className="font-normal text-slate-400">(optional)</span>
            </label>
            <textarea rows={3} className="field-input" {...fieldProps("description")} />
          </div>

          <div className="sm:col-span-2">
            <label htmlFor="bill_file" className="field-label">
              Itemised bill
            </label>
            <input
              id="bill_file"
              name="bill_file"
              type="file"
              accept={ACCEPT_ATTR}
              required
              disabled={submitting}
              aria-invalid={Boolean(errors.bill_file)}
              aria-describedby="bill_file-hint bill_file-error"
              className="block w-full rounded-md border border-slate-300 px-3 py-2 text-sm
                         file:mr-3 file:rounded file:border-0 file:bg-brand-50
                         file:px-3 file:py-1.5 file:text-sm file:font-medium
                         file:text-brand-700 hover:file:bg-brand-100"
              onChange={(event) => {
                setFile(event.target.files?.[0] ?? null);
                setErrors((current) => {
                  if (!current.bill_file) return current;
                  const next = { ...current };
                  delete next.bill_file;
                  return next;
                });
              }}
            />
            <p id="bill_file-hint" className="mt-1 text-xs text-slate-500">
              PDF, JPG or PNG, up to {MAX_SIZE_MB} MB.
              {file && ` Selected: ${file.name} (${formatFileSize(file.size)}).`}
            </p>
            {errors.bill_file && (
              <p id="bill_file-error" className="field-error">
                {errors.bill_file}
              </p>
            )}
          </div>
        </div>

        <div className="flex items-center gap-3 border-t border-slate-200 pt-5">
          <button type="submit" className="btn-primary" disabled={submitting}>
            {submitting ? <Spinner label="Submitting claim" /> : "Submit claim"}
          </button>
          <button
            type="button"
            className="btn-secondary"
            disabled={submitting}
            onClick={() => router.push("/claims")}
          >
            Cancel
          </button>
          {submitting && (
            <p className="text-sm text-slate-500">
              Uploading the bill and starting the assessment…
            </p>
          )}
        </div>
      </form>
    </div>
  );
}

export default function NewClaimPage() {
  return (
    <RouteGuard>
      <SubmitClaimForm />
    </RouteGuard>
  );
}
