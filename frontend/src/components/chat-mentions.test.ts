import { describe, expect, it } from "vitest";
import { filterMentionFiles, mentionSpan, stripMention } from "./chat-mentions";

const files = [
  { filename: "投资方向备忘.md" },
  { filename: "ETF行情快照.csv" },
  { filename: "月度复盘-2026-11.json" },
  { filename: "合同扫描件.pdf" },
];

describe("@ 引用工作台文件", () => {
  it("行首 @ 或空白后的 @ 才触发", () => {
    expect(mentionSpan("@投资")).toEqual({ start: 0, query: "投资" });
    expect(mentionSpan("看看 @ETF")).toEqual({ start: 3, query: "ETF" });
    expect(mentionSpan("@")).toEqual({ start: 0, query: "" });
  });

  it("邮箱和句中 @ 不触发", () => {
    expect(mentionSpan("a@b.com")).toBeNull();
    expect(mentionSpan("hello@world")).toBeNull();
    expect(mentionSpan("@投资 后面的字")).toBeNull();
  });

  it("文件名过滤忽略大小写，空词返回全部并限流", () => {
    expect(filterMentionFiles(files, "etf")).toEqual([{ filename: "ETF行情快照.csv" }]);
    expect(filterMentionFiles(files, "复盘")).toEqual([
      { filename: "月度复盘-2026-11.json" },
    ]);
    expect(filterMentionFiles(files, "", 2)).toHaveLength(2);
  });

  it("选中后去掉触发词，避免把半截 @ 发给模型", () => {
    expect(stripMention("看看 @投", 3)).toBe("看看");
    expect(stripMention("@投", 0)).toBe("");
    expect(stripMention("看看 @投 后面", 3)).toBe("看看 @投 后面");
  });
});
