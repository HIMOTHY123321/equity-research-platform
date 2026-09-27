import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const pushMock = vi.fn();
let searchParams = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
  useSearchParams: () => searchParams,
}));

import LoginPage from "./page";
import { AuthProvider } from "@/lib/auth-context";
import * as api from "@/lib/api";

describe("LoginPage (Phase 16.1)", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    pushMock.mockClear();
    searchParams = new URLSearchParams();
    vi.spyOn(api, "getCurrentUser").mockResolvedValue(null);
  });

  it("submitting valid credentials signs in and redirects to / by default", async () => {
    vi.spyOn(api, "login").mockResolvedValue({
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
        <LoginPage />
      </AuthProvider>,
    );

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "trader@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "hunter2hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(api.login).toHaveBeenCalledWith("trader@example.com", "hunter2hunter2"));
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/"));
  });

  it("redirects to ?next= after a successful login (redirect-back)", async () => {
    searchParams = new URLSearchParams("next=/settings");
    vi.spyOn(api, "login").mockResolvedValue({
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
        <LoginPage />
      </AuthProvider>,
    );

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "trader@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "hunter2hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/settings"));
  });

  it("shows an error message and does not redirect on invalid credentials", async () => {
    vi.spyOn(api, "login").mockRejectedValue(new api.ApiError(401, "Invalid email or password"));

    render(
      <AuthProvider>
        <LoginPage />
      </AuthProvider>,
    );

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "trader@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "wrongpassword" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(screen.getByText("Invalid email or password")).toBeInTheDocument());
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("never sends an untrusted ?next= value that doesn't start with /", async () => {
    searchParams = new URLSearchParams("next=https://evil.example.com");
    vi.spyOn(api, "login").mockResolvedValue({
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
        <LoginPage />
      </AuthProvider>,
    );

    fireEvent.change(screen.getByLabelText("Email"), { target: { value: "trader@example.com" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "hunter2hunter2" } });
    fireEvent.click(screen.getByRole("button", { name: "Sign in" }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/"));
  });
});
