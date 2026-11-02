/** 语音播报纯逻辑测试：用假 speechSynthesis 验证 speak/stop/截断。 */
import { describe, expect, it, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useSpeech } from "./use-speech";

class FakeUtterance {
  text: string;
  lang = "";
  rate = 1;
  pitch = 1;
  voice: unknown = null;
  onend: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(text: string) {
    this.text = text;
  }
}

const spoken: FakeUtterance[] = [];
let cancelled = 0;

beforeEach(() => {
  spoken.length = 0;
  cancelled = 0;
  (window as unknown as Record<string, unknown>).SpeechSynthesisUtterance = FakeUtterance;
  (window as unknown as Record<string, unknown>).speechSynthesis = {
    getVoices: () => [],
    speak: (u: FakeUtterance) => spoken.push(u),
    cancel: () => {
      cancelled += 1;
    },
  };
});

describe("useSpeech", () => {
  it("朗读时传入 lang 且默认中文语音", () => {
    const { result } = renderHook(() => useSpeech());
    act(() => result.current.speak("本月支出 5000 元", "zh"));
    expect(spoken).toHaveLength(1);
    expect(spoken[0].lang).toBe("zh-CN");
    expect(spoken[0].text).toContain("本月支出");
  });

  it("超过 1200 字截断并标记", () => {
    const { result } = renderHook(() => useSpeech());
    act(() => result.current.speak("字".repeat(2000), "zh"));
    expect(spoken[0].text.length).toBeLessThan(1300);
    expect(result.current.truncated).toBe(true);
  });

  it("markdown 代码块被替换而不是朗读", () => {
    const { result } = renderHook(() => useSpeech());
    act(() => result.current.speak("结论\n```js\nconst a=1\n```", "zh"));
    expect(spoken[0].text).not.toContain("const a=1");
    expect(spoken[0].text).toContain("代码块略");
  });

  it("再次朗读会先取消上一次", () => {
    const { result } = renderHook(() => useSpeech());
    act(() => result.current.speak("第一段", "zh"));
    act(() => result.current.speak("第二段", "zh"));
    expect(cancelled).toBeGreaterThanOrEqual(2);
  });
});
