import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiDownload, saveBlob, setToken } from "@/lib/api";

/**
 * 下载链路守卫。
 *
 * 曾经的写法是 `a.href = "/api/export/report?lang=zh"` 直接让浏览器下载。
 * 同源 GET 不会带 `Authorization`，所以一旦实例配了口令或启用了账号体系，
 * 后端返回 401，而 `a.click()` 不会抛错 —— 界面照样提示"已下载"，
 * 用户拿到的是一个 401 页面。这类故障只有真实用户会踩到，测试必须钉住。
 */
/** 拦截 <a> 的 click：jsdom 会尝试真实导航并报 "Not implemented: navigation"。 */
function interceptAnchorClicks(sink: string[]): void {
  const realCreate = document.createElement.bind(document);
  vi.spyOn(document, "createElement").mockImplementation((tag: string) => {
    const el = realCreate(tag) as HTMLElement;
    if (tag === "a") {
      (el as HTMLAnchorElement).click = vi.fn(() => {
        sink.push((el as HTMLAnchorElement).download);
      });
    }
    return el;
  });
}

describe("apiDownload", () => {
  let created: string[];

  beforeEach(() => {
    created = [];
    // jsdom 没有 createObjectURL / revokeObjectURL
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:mock"),
      revokeObjectURL: vi.fn(),
    });
    interceptAnchorClicks(created);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("带上 Authorization 头，并把 blob 存成文件", async () => {
    setToken("tk-123");
    const fetchMock = vi.fn(async (_url: string, init: RequestInit) => {
      const h = new Headers(init.headers);
      expect(h.get("Authorization")).toBe("Bearer tk-123");
      return new Response(new Blob(["<html>report</html>"], { type: "text/html" }), {
        status: 200,
      });
    });
    vi.stubGlobal("fetch", fetchMock);

    await apiDownload("/api/export/report?lang=zh", "报告.html");
    expect(created).toEqual(["报告.html"]);
  });

  it("401 时必须抛错（而不是假装下载成功）", async () => {
    setToken("");
    const fetchMock = vi.fn(
      async () => new Response(JSON.stringify({ error: "需要访问口令" }), { status: 401 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiDownload("/api/export/report", "r.html")).rejects.toThrow();
    expect(created).toEqual([]); // 没有触发下载
  });

  it("5xx 给出人能读懂的话，而不是裸状态码", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response("bad gateway", { status: 502 })),
    );
    await expect(apiDownload("/api/export/csv", "x.csv")).rejects.toThrow(/服务暂时不可用|下载失败/);
  });
});

describe("saveBlob", () => {
  it("click 之后立刻 revoke，不占内存", () => {
    interceptAnchorClicks([]);
    const revoke = vi.fn();
    vi.stubGlobal("URL", { createObjectURL: vi.fn(() => "blob:x"), revokeObjectURL: revoke });
    saveBlob(new Blob(["a"]), "a.txt");
    expect(revoke).toHaveBeenCalledWith("blob:x");
  });
});
