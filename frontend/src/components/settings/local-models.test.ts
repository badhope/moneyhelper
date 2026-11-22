import { describe, expect, it } from "vitest";
import { LOCAL_ENGINES, LOCAL_MODELS } from "./local-models";

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
    expect(LOCAL_MODELS.length).toBeGreaterThanOrEqual(4);
    const ids = new Set(LOCAL_MODELS.map((m) => m.id));
    expect(ids.size).toBe(LOCAL_MODELS.length);
    for (const m of LOCAL_MODELS) {
      for (const e of LOCAL_ENGINES) {
        expect(m.endpoints[e.id]).toBeTruthy();
      }
      expect(m.downloadUrl).toMatch(/^https:\/\//);
    }
  });
});
