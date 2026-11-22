import { describe, expect, it } from "vitest";
import { mapRunsToMessages, streamEventPatch } from "./chat-view-hooks";
import type { RunRecord } from "@/lib/types";
import type { StepInfo } from "@/components/ChatMessageBubble";
import type { AgentToolStep } from "@/lib/types";

/** 构造 streamEventPatch 适用的累加器（类型与源码参数类型对齐） */
function makeAcc() {
  return {
    text: "",
    steps: [] as StepInfo[],
    tools: [] as AgentToolStep[],
    thinking: [] as string[],
    agentStatus: undefined as "running" | "done" | undefined,
  };
}

/** 构造最小 RunRecord：只填 mapRunsToMessages 需要的字段 */
function makeRun(over: Partial<RunRecord>): RunRecord {
  return {
    id: over.id ?? 1,
    thread_id: over.thread_id ?? "thread-test",
    question: over.question ?? "测试问题",
    answer: over.answer ?? "测试回答",
    level: over.level ?? "L1 洞察",
    flags: over.flags ?? [],
    created_at: over.created_at ?? "2026-01-01T00:00:00Z",
    route: over.route ?? "general",
    route_reason: over.route_reason ?? "",
    llm: over.llm,
    tools: over.tools ?? [],
    actions: over.actions ?? [],
    attachments: over.attachments ?? [],
  };
}

describe("mapRunsToMessages", () => {
  it("空输入返回空数组", () => {
    expect(mapRunsToMessages([])).toEqual([]);
  });

  it("按 ID 倒序（最新在前）：输入 [1,2] → 输出 Q2 在 Q1 之前", () => {
    const runs = [
      makeRun({ id: 1, question: "Q1", answer: "A1" }),
      makeRun({ id: 2, question: "Q2", answer: "A2" }),
    ];
    const msgs = mapRunsToMessages(runs);
    expect(msgs).toHaveLength(4);
    // reverse(): id=2 最新 → 最先输出
    expect(msgs[0].role).toBe("user");
    expect(msgs[0].text).toBe("Q2");
    expect(msgs[1].role).toBe("assistant");
    expect(msgs[1].text).toBe("A2");
    expect(msgs[2].role).toBe("user");
    expect(msgs[2].text).toBe("Q1");
    expect(msgs[3].role).toBe("assistant");
    expect(msgs[3].text).toBe("A1");
  });

  it("assistant 消息携带 runId / meta", () => {
    const runs = [makeRun({ id: 42, answer: "meta-test" })];
    const msgs = mapRunsToMessages(runs);
    const a = msgs[1];
    expect(a.runId).toBe(42);
    expect(a.meta?.answer).toBe("meta-test");
  });

  it("user 消息不带 runId", () => {
    const msgs = mapRunsToMessages([makeRun({ id: 9 })]);
    expect(msgs[0].runId).toBeUndefined();
  });

  it("user 消息携带已发送附件引用", () => {
    const runs = [makeRun({
      id: 11,
      attachments: [{ id: 7, filename: "note.md", kind: "text" }],
    })];
    const msgs = mapRunsToMessages(runs);
    expect(msgs[0].attachments).toEqual([
      { id: 7, filename: "note.md", kind: "text" },
    ]);
  });
});

describe("streamEventPatch", () => {
  it("累加器初始状态为空", () => {
    const acc = makeAcc();
    expect(acc.text).toBe("");
  });

  it("token 事件追加到 text 并返回 patch", () => {
    const acc = { ...makeAcc(), text: "你好" };
    const patch = streamEventPatch(acc, { type: "token", data: { content: "世界" } });
    expect(acc.text).toBe("你好世界");
    expect(patch).toEqual({ text: "你好世界" });
  });

  it("text 事件兼容旧 delta 格式", () => {
    const acc = { ...makeAcc(), text: "前缀" };
    const patch = streamEventPatch(acc, { type: "text", delta: "后缀" });
    expect(acc.text).toBe("前缀后缀");
    expect(patch).toEqual({ text: "前缀后缀" });
  });

  it("plan 事件更新 plan 字段", () => {
    const acc = makeAcc();
    const patch = streamEventPatch(acc, {
      type: "plan",
      data: { steps: [{ id: "1", label: "分析" }], mode: "deterministic", route: "market" },
    });
    expect(patch!.plan?.steps[0].label).toBe("分析");
    expect(patch!.plan?.route).toBe("market");
  });

  it("tool 事件首次出现时 push 新工具", () => {
    const acc = makeAcc();
    const patch = streamEventPatch(acc, {
      type: "tool",
      data: { id: "t1", name: "get_quote", status: "running", summary: "查询中" },
    });
    expect(acc.tools).toHaveLength(1);
    expect(acc.tools[0].name).toBe("get_quote");
    expect(acc.tools[0].status).toBe("running");
    expect(patch).toEqual({ tools: acc.tools });
  });

  it("tool 事件更新已有工具状态（同 id 不重复 push）", () => {
    const acc = makeAcc();
    streamEventPatch(acc, { type: "tool", data: { id: "t1", status: "running" } });
    const patch = streamEventPatch(acc, { type: "tool", data: { id: "t1", status: "done", summary: "完成" } });
    expect(acc.tools).toHaveLength(1);
    expect(acc.tools[0].status).toBe("done");
    expect(acc.tools[0].summary).toBe("完成");
    expect(patch).toEqual({ tools: acc.tools });
  });

  it("step 事件 phase=done 时 push 步骤", () => {
    const acc = makeAcc();
    const patch = streamEventPatch(acc, { type: "step", id: "s1", phase: "done", label: "分类", detail: "action" });
    expect(acc.steps).toHaveLength(1);
    expect(acc.steps[0].label).toBe("分类");
    expect(patch).toEqual({ steps: [...acc.steps] });
  });

  it("step 事件 phase != done 时不 push", () => {
    const acc = makeAcc();
    const patch = streamEventPatch(acc, { type: "step", id: "s1", phase: "start", label: "分类", detail: "" });
    expect(acc.steps).toHaveLength(0);
    expect(patch).toBeNull();
  });

  it("thinking 事件追加思考内容", () => {
    const acc = makeAcc();
    const patch = streamEventPatch(acc, { type: "thinking", data: { content: "正在推理..." } });
    expect(acc.thinking).toEqual(["正在推理..."]);
    expect(patch).toEqual({ thinking: ["正在推理..."] });
  });

  it("agent 事件更新 agentStatus", () => {
    const acc = makeAcc();
    const patch = streamEventPatch(acc, { type: "agent", data: { status: "running" } });
    expect(acc.agentStatus).toBe("running");
    expect(patch).toEqual({ agentStatus: "running" });
  });

  it("final 事件设置最终 answer + meta", () => {
    const acc = makeAcc();
    const patch = streamEventPatch(acc, {
      type: "final",
      answer: "结论：建议持有",
      level: "L2 决策",
      route: "action",
      route_reason: "风控通过",
      metrics: { confidence: 0.9 },
      flags: [{ code: "OK", text: "健康" }],
      llm: "llm",
      tools: ["get_quote"],
      actions: [{ tab: "features" }],
    });
    expect(patch!.text).toBe("结论：建议持有");
    expect(patch!.meta?.level).toBe("L2 决策");
    expect(patch!.meta?.route).toBe("action");
    expect(patch!.actions?.[0]?.tab).toBe("features");
  });

  it("final 事件 pending_token 产生 pending", () => {
    const acc = makeAcc();
    const patch = streamEventPatch(acc, { type: "final", answer: "待确认", pending_token: "tok123", pending_summary: "买 100 股" });
    expect(patch!.pending?.token).toBe("tok123");
    expect(patch!.pending?.summary).toBe("买 100 股");
  });

  it("error 事件返回 error patch", () => {
    const acc = makeAcc();
    const patch = streamEventPatch(acc, { type: "error", message: "模型超时" });
    expect(patch).toEqual({ error: "模型超时" });
  });

  it("未知事件返回 null", () => {
    const acc = makeAcc();
    const patch = streamEventPatch(acc, { type: "unknown_event" });
    expect(patch).toBeNull();
  });
});
