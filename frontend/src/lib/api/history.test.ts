import { afterEach, describe, expect, it, vi } from "vitest";
import { searchHistory } from "./history";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("searchHistory", () => {
  it("只取紧凑命中，并带上关键词与会话定位字段", async () => {
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) => new Response(
      JSON.stringify({
        results: [{
          id: 12,
          thread_id: "hs-1",
          session_title: "本月支出",
          role: "answer",
          snippet: "这个月一共花了 3200 元…",
          created_at: "2026-11-22 20:00:00",
          archived: false,
        }],
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    ));
    vi.stubGlobal("fetch", fetchMock);

    const rows = await searchHistory("  花了  ", 20);
    expect(rows).toHaveLength(1);
    expect(rows[0].thread_id).toBe("hs-1");
    expect(rows[0].snippet).toContain("花了");

    const url = String(fetchMock.mock.calls[0][0]);
    expect(url).toContain("/api/history?q=");
    expect(url).toContain("compact=1");
    expect(url).toContain("limit=20");
    expect(url).toContain(encodeURIComponent("花了"));
  });

  it("空搜索词不发请求", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);
    await expect(searchHistory("   ")).resolves.toEqual([]);
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
