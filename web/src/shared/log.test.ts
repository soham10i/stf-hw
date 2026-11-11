import { afterEach, describe, expect, it, vi } from "vitest";
import { log, quiet } from "./log";

afterEach(() => vi.restoreAllMocks());

describe("quiet", () => {
  it("resolves a best-effort failure to its fallback and logs it with its scope", async () => {
    const debug = vi.spyOn(console, "debug").mockImplementation(() => {});
    const out = await Promise.reject(new Error("offline")).catch(quiet("records", null));
    expect(out).toBeNull();
    expect(debug).toHaveBeenCalledWith("[stf:records]", "ignored failure:", expect.any(Error));
  });

  it("resolves to undefined without a fallback", async () => {
    vi.spyOn(console, "debug").mockImplementation(() => {});
    expect(await Promise.reject(new Error("x")).catch(quiet("track"))).toBeUndefined();
  });
});

describe("log", () => {
  it("always prints errors, tagged with the scope", () => {
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    log.error("scene", "boom");
    expect(error).toHaveBeenCalledWith("[stf:scene]", "boom");
  });
});
