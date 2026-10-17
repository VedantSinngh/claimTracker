/**
 * src/components/RouteGuard.test.tsx
 * ───────────────────────────────────
 * The guard decides what a signed-in user is allowed to see, so the cases
 * that matter are: it must not flash protected content while the session is
 * still resolving, and the wrong role must get an explanation rather than a
 * redirect loop.
 *
 * AuthProvider is bypassed here — these tests mock `useAuth` directly so each
 * auth state can be driven without a fetch.
 */
import { render, screen } from "@testing-library/react";

import type { Role, UserResponse } from "@/lib/api/types";
import type { AuthStatus } from "@/lib/auth/AuthProvider";

import { RouteGuard } from "./RouteGuard";

const mockReplace = jest.fn();

jest.mock("next/navigation", () => ({
  useRouter: () => ({ replace: mockReplace, push: jest.fn() }),
}));

let authState: { status: AuthStatus; user: UserResponse | null } = {
  status: "loading",
  user: null,
};

jest.mock("@/lib/auth/AuthProvider", () => ({
  useAuth: () => authState,
}));

function userWithRole(role: Role): UserResponse {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    email: "someone@example.com",
    full_name: "Someone",
    role,
    is_active: true,
  };
}

beforeEach(() => {
  mockReplace.mockClear();
});

describe("RouteGuard", () => {
  it("shows a spinner and no content while the session is resolving", () => {
    authState = { status: "loading", user: null };
    render(
      <RouteGuard>
        <p>secret</p>
      </RouteGuard>,
    );

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
    // Critically, it must not redirect yet.
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("redirects an anonymous visitor to the sign-in page", () => {
    authState = { status: "anonymous", user: null };
    render(
      <RouteGuard>
        <p>secret</p>
      </RouteGuard>,
    );

    expect(mockReplace).toHaveBeenCalledTimes(1);
    expect(mockReplace.mock.calls[0][0]).toContain("/login");
    expect(screen.queryByText("secret")).not.toBeInTheDocument();
  });

  it("renders the page for a signed-in user when no role is required", () => {
    authState = { status: "authenticated", user: userWithRole("user") };
    render(
      <RouteGuard>
        <p>secret</p>
      </RouteGuard>,
    );

    expect(screen.getByText("secret")).toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("renders the page when the user holds one of the required roles", () => {
    authState = { status: "authenticated", user: userWithRole("admin") };
    render(
      <RouteGuard roles={["reviewer", "admin"]}>
        <p>queue</p>
      </RouteGuard>,
    );

    expect(screen.getByText("queue")).toBeInTheDocument();
  });

  it("explains the refusal instead of redirecting on a role mismatch", () => {
    authState = { status: "authenticated", user: userWithRole("user") };
    render(
      <RouteGuard roles={["admin"]}>
        <p>admin only</p>
      </RouteGuard>,
    );

    expect(screen.queryByText("admin only")).not.toBeInTheDocument();
    expect(screen.getByText(/do not have access/i)).toBeInTheDocument();
    // A redirect here would bounce the user between pages.
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("names both the required and the actual role", () => {
    authState = { status: "authenticated", user: userWithRole("reviewer") };
    render(
      <RouteGuard roles={["admin"]}>
        <p>admin only</p>
      </RouteGuard>,
    );

    const alert = screen.getByRole("status");
    expect(alert).toHaveTextContent("admin");
    expect(alert).toHaveTextContent("reviewer");
  });
});
