import { describe, expect, it } from "vitest";
import { ApiError, errorOf } from "./api";

describe("ApiError", () => {
  it("reads the coded body's message, code and request id", () => {
    const e = new ApiError({ code: "rate_limited", reason: "daily_budget_spent", status: 429,
      message: "today's question budget is used up", request_id: "5f0c9a1e2b7d4c38" });
    expect(e.message).toBe("today's question budget is used up");
    expect([e.code, e.reason, e.status, e.requestId]).toEqual(
      ["rate_limited", "daily_budget_spent", 429, "5f0c9a1e2b7d4c38"]);
  });

  it("falls back to an older server's error or detail, then to the status", () => {
    expect(new ApiError({ error: "too often" }, 429).message).toBe("too often");
    expect(new ApiError({ detail: "no such session" }, 404).message).toBe("no such session");
    expect(new ApiError({}, 502).message).toBe("HTTP 502");
    expect(new ApiError({}, undefined, "the copilot failed").message).toBe("the copilot failed");
  });

  it("is built from a response whose body is not JSON", async () => {
    const e = await errorOf(new Response("<html>", { status: 503 }));
    expect(e.message).toBe("HTTP 503");
    expect(e.status).toBe(503);
  });
});
