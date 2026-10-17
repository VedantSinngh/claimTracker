/**
 * src/lib/api/client.test.ts
 * ───────────────────────────
 * The client is the only thing that talks to the backend, so its error
 * shaping is what every page branches on. FastAPI returns three different
 * error body shapes and these tests pin the flattening of all three, plus the
 * multipart construction for the two upload endpoints.
 */
import { ApiError, claimsApi, clearToken, getToken, setToken } from "./client";

const fetchMock = jest.fn();

beforeAll(() => {
  global.fetch = fetchMock as unknown as typeof fetch;
});

beforeEach(() => {
  fetchMock.mockReset();
  clearToken();
});

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    text: async () => JSON.stringify(body),
  } as Response;
}

describe("token storage", () => {
  it("round-trips the token", () => {
    expect(getToken()).toBeNull();
    setToken("abc.def.ghi");
    expect(getToken()).toBe("abc.def.ghi");
    clearToken();
    expect(getToken()).toBeNull();
  });
});

describe("auth header", () => {
  it("attaches the bearer token when one is stored", async () => {
    setToken("my-token");
    fetchMock.mockResolvedValue(jsonResponse({ items: [], total: 0, page: 1, page_size: 20 }));

    await claimsApi.list();

    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers.Authorization).toBe("Bearer my-token");
  });

  it("omits the header when there is no token", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [], total: 0, page: 1, page_size: 20 }));

    await claimsApi.list();

    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers.Authorization).toBeUndefined();
  });
});

describe("error shaping", () => {
  it("reads {detail: string}, the shape our own handlers return", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "Claim not found" }, 404));

    await expect(claimsApi.get("abc")).rejects.toMatchObject({
      status: 404,
      detail: "Claim not found",
    });
  });

  it("flattens Pydantic's 422 list into field errors", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        {
          detail: [
            { loc: ["body", "claim_amount"], msg: "Input should be greater than 0", type: "x" },
            { loc: ["body", "patient_name"], msg: "String too short", type: "y" },
          ],
        },
        422,
      ),
    );

    const error = await claimsApi.get("abc").catch((cause) => cause);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(422);
    expect(error.fieldErrors).toEqual([
      { field: "claim_amount", message: "Input should be greater than 0" },
      { field: "patient_name", message: "String too short" },
    ]);
    expect(error.detail).toContain("2 fields");
  });

  it("names the field when a 422 has only one error", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        { detail: [{ loc: ["body", "email"], msg: "not a valid email", type: "x" }] },
        422,
      ),
    );

    const error = await claimsApi.get("abc").catch((cause) => cause);
    expect(error.detail).toBe("email: not a valid email");
  });

  it("marks 401 as an auth error so callers can sign the user out", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "Invalid or expired token" }, 401));

    const error = await claimsApi.get("abc").catch((cause) => cause);
    expect(error.isAuthError).toBe(true);
    expect(error.isForbidden).toBe(false);
  });

  it("marks 403 as forbidden rather than as an auth error", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: "Role 'user' is not permitted" }, 403));

    const error = await claimsApi.get("abc").catch((cause) => cause);
    expect(error.isForbidden).toBe(true);
    expect(error.isAuthError).toBe(false);
  });

  it("explains a network failure instead of leaking the raw TypeError", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    const error = await claimsApi.get("abc").catch((cause) => cause);
    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(0);
    expect(error.detail).toMatch(/Is the backend running/);
  });

  it("still throws usefully when the error body is not JSON", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 502,
      text: async () => "<html>Bad Gateway</html>",
    } as Response);

    const error = await claimsApi.get("abc").catch((cause) => cause);
    expect(error.status).toBe(502);
    expect(error.detail).toContain("502");
  });
});

describe("responses", () => {
  it("returns parsed JSON on success", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ items: [], total: 0, page: 1, page_size: 20 }),
    );

    const result = await claimsApi.list();
    expect(result.total).toBe(0);
  });

  it("handles a 204 with no body, as DELETE /exclusions returns", async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 204, text: async () => "" } as Response);

    const { exclusionsApi } = await import("./client");
    await expect(exclusionsApi.remove("some-id")).resolves.toBeUndefined();
  });
});

describe("query building", () => {
  it("sends paging and the status filter", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [], total: 0, page: 2, page_size: 10 }));

    await claimsApi.list({ status: "NEEDS_REVIEW", page: 2, pageSize: 10 });

    const url = fetchMock.mock.calls[0][0] as string;
    expect(url).toContain("status=NEEDS_REVIEW");
    expect(url).toContain("page=2");
    expect(url).toContain("page_size=10");
  });

  it("omits the status parameter when no filter is set", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [], total: 0, page: 1, page_size: 20 }));

    await claimsApi.list({ status: "" });

    expect(fetchMock.mock.calls[0][0] as string).not.toContain("status=");
  });
});

describe("claim submission", () => {
  it("builds the multipart body the Form(...) endpoint expects", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: "new-claim" }, 201));
    const file = new File(["%PDF-1.4"], "bill.pdf", { type: "application/pdf" });

    await claimsApi.submit(
      {
        patient_name: "John Smith",
        claim_item: "Hospitalisation",
        reason: "Acute appendicitis",
        address: "45 Maple Avenue",
        date_of_treatment: "2024-03-15",
        medical_facility: "Metropolitan General Hospital",
        claim_amount: 9860,
      },
      file,
    );

    const init = fetchMock.mock.calls[0][1];
    const body = init.body as FormData;
    expect(body).toBeInstanceOf(FormData);
    expect(body.get("patient_name")).toBe("John Smith");
    expect(body.get("claim_amount")).toBe("9860");
    expect(body.get("bill_file")).toBe(file);
    // Omitted optional fields must not be sent as "undefined".
    expect(body.get("description")).toBeNull();
  });

  it("never sets Content-Type for multipart, so the browser picks the boundary", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: "new-claim" }, 201));
    const file = new File(["x"], "bill.png", { type: "image/png" });

    await claimsApi.submit(
      {
        patient_name: "A",
        claim_item: "B",
        reason: "C",
        address: "D",
        date_of_treatment: "2024-01-01",
        medical_facility: "E",
        claim_amount: 1,
      },
      file,
    );

    const headers = fetchMock.mock.calls[0][1].headers as Record<string, string>;
    expect(headers["Content-Type"]).toBeUndefined();
  });
});

describe("review submission", () => {
  it("sends JSON with a Content-Type", async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: "review-1" }, 201));

    await claimsApi.review("claim-1", { outcome: "OVERRIDE", new_status: "ACCEPTED", comment: "ok" });

    const init = fetchMock.mock.calls[0][1];
    const headers = init.headers as Record<string, string>;
    expect(headers["Content-Type"]).toBe("application/json");
    expect(JSON.parse(init.body as string)).toEqual({
      outcome: "OVERRIDE",
      new_status: "ACCEPTED",
      comment: "ok",
    });
  });
});
