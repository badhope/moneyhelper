import { describe, expect, it } from "vitest";
import { normalizeBrowserUrl } from "./workbench";

describe("normalizeBrowserUrl", () => {
  it("裸域名补 https", () => {
    expect(normalizeBrowserUrl("quote.eastmoney.com")).toBe("https://quote.eastmoney.com/");
  });
  it("保留合法 http(s) 地址", () => {
    expect(normalizeBrowserUrl("https://xueqiu.com/")).toBe("https://xueqiu.com/");
  });
  it("拒绝 javascript: 伪协议", () => {
    expect(normalizeBrowserUrl("javascript:alert(1)")).toBe("");
    expect(normalizeBrowserUrl("data:text/html,<script>alert(1)</script>")).toBe("");
  });
  it("中文词转搜索", () => {
    expect(normalizeBrowserUrl("沪深300 行情")).toContain("baidu.com/s?wd=");
  });
  it("空输入返回空", () => {
    expect(normalizeBrowserUrl("   ")).toBe("");
  });
});
