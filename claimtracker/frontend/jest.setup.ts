import "@testing-library/jest-dom";

// next/navigation is unavailable outside the App Router runtime; tests that
// care about navigation assert on these mocks.
jest.mock("next/navigation", () => ({
  useRouter: () => ({
    push: jest.fn(),
    replace: jest.fn(),
    refresh: jest.fn(),
    back: jest.fn(),
  }),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));
