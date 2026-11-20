/**
 * apiStream 断线重连语义（弱网下最容易出错的一段，之前只有逻辑审视、没有测试）。
 *
 * 用 mock 的 fetchEventSource 模拟四种真实断法：
 * 1. 一帧没收到就断（反代超时 / 204）→ 指数退避重试，最多 5 次
 * 2. 收到半截内容后断 → 立即报错，不重放（重放会把半段回答重复一遍）
 * 3. 收到 done → 正常结束
 * 4. 连接"正常"关闭但没有 done → 视为断流，不能当成功
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

type Behaviour =
  | { kind: "error" }
  | { kind: "lines"; lines: unknown[] }
  | { kind: "done" }
  | { kind: "close" };

const h = vi.hoisted(() => ({
  calls: [] as string[],
  behaviours: [] as Behaviour[],
}));

vi.mock("@microsoft/fetch-event-source", () => ({
  fetchEventSource: async (path: string, opts: { onmessage: (ev: { data: string }) => void }) => {
    h.calls.push(path);
    const b = h.behaviours.shift();
    if (!b || b.kind === "error") throw new Error("network down");
    if (b.kind === "close") return;
    if (b.kind === "lines") {
      for (const line of b.lines) opts.onmessage({ data: JSON.stringify(line) });
      throw new Error("connection closed mid-stream");
    }
    opts.onmessage({ data: JSON.stringify({ type: "done" }) });
  },
}));

import { apiStream } from "./api";

beforeEach(() => {
  h.calls.length = 0;
  h.behaviours.length = 0;
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("apiStream 弱网断线", () => {
  it("一帧未收到：按 1/2/4/8/16s 退避重试 5 次后放弃", async () => {
    for (let i = 0; i < 6; i += 1) h.behaviours.push({ kind: "error" });

    const settled = apiStream("/api/qa/stream", {}, () => {}).catch((e: Error) => e);
    await vi.advanceTimersByTimeAsync(32_000);
    const err = await settled;

    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toContain("已重试 5 次");
    expect(h.calls).toHaveLength(6); // 首发 1 次 + 重试 5 次
  });

  it("收到半截内容后断连：立即报错，不重放", async () => {
    h.behaviours.push({ kind: "lines", lines: [{ type: "delta", text: "半" }] });

    const err = await apiStream("/api/qa/stream", {}, () => {}).catch((e: Error) => e);

    // 已收到内容时把原始断连原因抛给调用方（不重放、也不掩成泛化文案）
    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toContain("connection closed mid-stream");
    expect(h.calls).toHaveLength(1);
  });

  it("连接正常关闭但没有 done：视为断流，不能当成功", async () => {
    h.behaviours.push({ kind: "close" });

    const settled = apiStream("/api/qa/stream", {}, () => {}).catch((e: Error) => e);
    await vi.advanceTimersByTimeAsync(32_000);
    const err = await settled;

    // "关闭但无 done" 走的是重试路径，不是在第一次就当成功返回
    expect(err).toBeInstanceOf(Error);
    expect((err as Error).message).toContain("已重试 5 次");
    expect(h.calls).toHaveLength(6);
  });

  it("收到 done 帧：正常结束且不重试", async () => {
    h.behaviours.push({ kind: "done" });

    await expect(apiStream("/api/qa/stream", {}, () => {})).resolves.toBeUndefined();
    expect(h.calls).toHaveLength(1);
  });
});
