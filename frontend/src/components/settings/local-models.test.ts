import { describe, expect, it } from "vitest";
import {
  LOCAL_ENGINES,
  LOCAL_MODELS,
  findInstalledModel,
  normalizeModelId,
} from "./local-models";

describe("local model entries", () => {
  it("每个推理端都指向本机 OpenAI 兼容端点", () => {
    expect(LOCAL_ENGINES).toHaveLength(4);
    for (const e of LOCAL_ENGINES) {
      expect(e.base).toMatch(/^http:\/\/127\.0\.0\.1:\d+\/v1$/);
      expect(e.defaultModel).toBeTruthy();
      expect(e.installUrl).toMatch(/^https:\/\//);
    }
  });

  it("每个精选模型都能在四个端上填入具体模型名", () => {
    expect(LOCAL_MODELS.length).toBeGreaterThanOrEqual(6);
    const ids = new Set(LOCAL_MODELS.map((m) => m.id));
    expect(ids.size).toBe(LOCAL_MODELS.length);
    for (const m of LOCAL_MODELS) {
      for (const e of LOCAL_ENGINES) {
        expect(m.endpoints[e.id]).toBeTruthy();
      }
      expect(m.downloadUrl).toMatch(/^https:\/\//);
    }
  });

  it("模型匹配只认探测返回的真实清单", () => {
    expect(findInstalledModel("", [{ id: "qwen3:4b" }])).toBeNull();
    expect(
      findInstalledModel("qwen3:4b-instruct-2507", [
        { id: "qwen3:4b-instruct-2507" },
        { id: "gemma3:4b" },
      ]),
    ).toBe("qwen3:4b-instruct-2507");
    // 大小写与首尾空白不影响精确匹配
    expect(findInstalledModel(" Qwen3-4B-Instruct-2507 ", [{ id: "qwen3-4b-instruct-2507" }])).toBe(
      "qwen3-4b-instruct-2507",
    );
    // llama.cpp 把本地文件路径当 id：按文件名包含匹配
    expect(
      findInstalledModel("MiniCPM5-2B", [{ id: "/models/MiniCPM5-2B-Q4_K_M.gguf" }]),
    ).toBe("/models/MiniCPM5-2B-Q4_K_M.gguf");
    // 没装就是 null，不做模糊猜测
    expect(findInstalledModel("qwen3:4b-instruct-2507", [{ id: "gemma3:4b" }])).toBeNull();
    expect(normalizeModelId("/models/Qwen3-4B.gguf")).toBe("models/qwen3-4b.gguf");
  });
});
