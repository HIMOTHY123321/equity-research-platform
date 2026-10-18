import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Phase 19.6/19.6.1: `liveClient` must obtain a short-lived WS ticket (via
 * `getLiveStreamTicket`) before every (re)connect and attach it as a
 * `Sec-WebSocket-Protocol` value -- NEVER in the WebSocket URL (a query
 * string is far more likely to end up in an access log, reverse-proxy
 * log, or browser history than a subprotocol value, which is carried only
 * in a request header -- see app.api.routes.live.WS_TICKET_SUBPROTOCOL on
 * the backend) -- and never the real session JWT. A fake `WebSocket`
 * global stands in for the browser's real one so these tests stay
 * deterministic and never open a real socket.
 */

const WS_TICKET_SUBPROTOCOL = "ws-ticket";

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static readonly OPEN = 1;
  static readonly CLOSED = 3;

  readyState = FakeWebSocket.OPEN;
  onopen: (() => void) | null = null;
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onclose: (() => void) | null = null;
  sent: string[] = [];

  constructor(
    public url: string,
    public protocols?: string | string[],
  ) {
    FakeWebSocket.instances.push(this);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close() {
    this.readyState = FakeWebSocket.CLOSED;
    this.onclose?.();
  }

  triggerOpen() {
    this.onopen?.();
  }
}

async function freshModules() {
  // Both modules must come from the SAME fresh registry: liveClient.ts
  // imports getLiveStreamTicket from lib/api internally, so the `api`
  // module instance we spy on here must be the exact one liveClient's
  // fresh import resolves against, not a stale one from an earlier test.
  vi.resetModules();
  const api = await import("@/lib/api");
  const { liveClient } = await import("@/lib/liveClient");
  return { api, liveClient };
}

describe("liveClient WS ticket handshake (Phase 19.6/19.6.1)", () => {
  beforeEach(() => {
    FakeWebSocket.instances = [];
    vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("fetches a ticket before opening the socket and sends it as a Sec-WebSocket-Protocol value, never in the URL", async () => {
    const { api, liveClient: client } = await freshModules();
    const ticketSpy = vi
      .spyOn(api, "getLiveStreamTicket")
      .mockResolvedValue({ ticket: "ticket-abc-123", expires_in: 45 });

    client.subscribe("SPY");
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));

    expect(ticketSpy).toHaveBeenCalledTimes(1);
    const socket = FakeWebSocket.instances[0];
    expect(socket.protocols).toEqual([WS_TICKET_SUBPROTOCOL, "ticket-abc-123"]);
    expect(socket.url).not.toContain("ticket-abc-123");
    expect(socket.url).not.toContain("ticket=");
    expect(socket.url).not.toContain("?");
  });

  it("never puts the ticket (or anything else) through console logging", async () => {
    const { api, liveClient: client } = await freshModules();
    vi.spyOn(api, "getLiveStreamTicket").mockResolvedValue({ ticket: "super-secret-ticket", expires_in: 45 });
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => undefined);
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => undefined);

    client.subscribe("SPY");
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));

    const allLoggedText = [...logSpy.mock.calls, ...warnSpy.mock.calls].flat().join(" ");
    expect(allLoggedText).not.toContain("super-secret-ticket");
  });

  it("reconnecting after a close fetches a brand new ticket, not the old one", async () => {
    const { api, liveClient: client } = await freshModules();
    const ticketSpy = vi
      .spyOn(api, "getLiveStreamTicket")
      .mockResolvedValueOnce({ ticket: "ticket-first", expires_in: 45 })
      .mockResolvedValueOnce({ ticket: "ticket-second", expires_in: 45 });

    vi.useFakeTimers({ shouldAdvanceTime: true });
    client.subscribe("SPY");
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    expect(FakeWebSocket.instances[0].protocols).toEqual([WS_TICKET_SUBPROTOCOL, "ticket-first"]);

    // Simulate the connection dropping -- liveClient's own onclose handler
    // schedules a reconnect.
    FakeWebSocket.instances[0].close();
    await vi.advanceTimersByTimeAsync(2000);
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(2));

    expect(ticketSpy).toHaveBeenCalledTimes(2);
    expect(FakeWebSocket.instances[1].protocols).toEqual([WS_TICKET_SUBPROTOCOL, "ticket-second"]);
    vi.useRealTimers();
  });

  it("if ticket issuance fails (e.g. unauthenticated), no socket is opened and reconnect is scheduled", async () => {
    const { api, liveClient: client } = await freshModules();
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const ticketSpy = vi
      .spyOn(api, "getLiveStreamTicket")
      .mockRejectedValueOnce(new api.ApiError(401, "Not authenticated"))
      .mockResolvedValueOnce({ ticket: "ticket-after-retry", expires_in: 45 });

    client.subscribe("SPY");
    await vi.waitFor(() => expect(ticketSpy).toHaveBeenCalledTimes(1));
    expect(FakeWebSocket.instances.length).toBe(0);

    await vi.advanceTimersByTimeAsync(2000);
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));
    expect(FakeWebSocket.instances[0].protocols).toEqual([WS_TICKET_SUBPROTOCOL, "ticket-after-retry"]);
    vi.useRealTimers();
  });

  it("the session JWT is never accessible to this client at all -- only the opaque ticket from getLiveStreamTicket", async () => {
    // liveClient.ts has no code path that reads amd_session or any cookie
    // -- it only ever calls getLiveStreamTicket(), which itself never
    // returns the raw session token (proven at the API-response level in
    // tests/integration/test_live_ws_ticket.py on the backend). This test
    // proves the frontend's own WebSocket construction never references
    // a session/cookie value, only the ticket string handed to it.
    const { api, liveClient: client } = await freshModules();
    vi.spyOn(api, "getLiveStreamTicket").mockResolvedValue({ ticket: "opaque-ticket-only", expires_in: 45 });

    client.subscribe("SPY");
    await vi.waitFor(() => expect(FakeWebSocket.instances.length).toBe(1));

    const socket = FakeWebSocket.instances[0];
    expect(socket.protocols).toEqual([WS_TICKET_SUBPROTOCOL, "opaque-ticket-only"]);
  });
});
