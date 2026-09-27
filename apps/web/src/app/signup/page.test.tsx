import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

import SignupPage from "./page";
import { AuthProvider } from "@/lib/auth-context";
import * as api from "@/lib/api";

describe("SignupPage (Phase 16.1)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    pushMock.mockClear();
    vi.spyOn(api, "getCurrentUser").mockResolvedValue(null);
  });

  it("submitting a valid email/password creates the account and redirects to /", async () => {
    vi.spyOn(api, "signup").mockResolvedValue({
      id: "u1",
      email: "trader@example.com",
      status: "active",
      role: "user",
      plan: "free",
      timezone: "America/New_York",
      created_at: "2026-01-01T00:00:00Z",
    });

    render(
      <AuthProvider>
        <SignupPage />
      </AuthProvider>,
    );

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "trader@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "hunter2hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() => expect(api.signup).toHaveBeenCalledWith("trader@example.com", "hunter2hunter2"));
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/"));
  });

  it("shows an error message when the email is already registered", async () => {
    vi.spyOn(api, "signup").mockRejectedValue(new api.ApiError(409, "trader@example.com is already registered"));

    render(
      <AuthProvider>
        <SignupPage />
      </AuthProvider>,
    );

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "trader@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "hunter2hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: "Create account" }));

    await waitFor(() =>
      expect(screen.getByText("trader@example.com is already registered")).toBeInTheDocument(),
    );
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("enforces an 8-character minimum on the password field", () => {
    render(
      <AuthProvider>
        <SignupPage />
      </AuthProvider>,
    );
    expect(screen.getByLabelText("Password")).toHaveAttribute("minLength", "8");
  });
});
