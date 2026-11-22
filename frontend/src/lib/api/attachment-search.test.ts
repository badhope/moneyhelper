import { afterEach, describe, expect, it, vi } from "vitest";
import { searchAttachments } from "./personal";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("searchAttachments", () => {
  it("把查询词和上限传给附件搜索接口", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(
      JSON.stringify({
        results: [{
          id: 3,
          filename: "预算笔记.md",
          kind: "text",
          size: 77,
          indexed: 0,
          created_at: "2026-11-22 20:00:00",
          snippet: "本月柠檬预算 300 元",
          match: "content",
        }],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);

    const rows = await searchAttachments("  柠檬  ", 10);
    expect(rows).toHaveLength(1);
    expect(rows[0].match).toBe("content");
    expect(rows[0].snippet).toContain("柠檬");

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/api/attachments/search?q=");
    expect(url).toContain("limit=10");
    expect(url).toContain(encodeURIComponent("柠檬"));
  });

  it("空查询不请求", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(searchAttachments("   ")).resolves.toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
