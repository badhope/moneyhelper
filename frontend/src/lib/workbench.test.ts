import { describe, expect, it } from "vitest";
import {
  OPEN_ATTACHMENT_EVENT,
  normalizeBrowserUrl,
  requestOpenAttachment,
} from "./workbench";

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

describe("requestOpenAttachment", () => {
  it("派发附件 id，忽略非法值", () => {
    let got = 0;
    const onOpen = (e: Event) => {
      got = (e as CustomEvent<{ id: number }>).detail.id;
    };
    window.addEventListener(OPEN_ATTACHMENT_EVENT, onOpen);
    requestOpenAttachment(42);
    expect(got).toBe(42);
    requestOpenAttachment(0);
    expect(got).toBe(42);
    window.removeEventListener(OPEN_ATTACHMENT_EVENT, onOpen);
  });
});
