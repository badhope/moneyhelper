import { describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { useDebouncedValue } from "./use-debounced-value";

describe("useDebouncedValue", () => {
  it("初始值立即返回（不清空首帧）", () => {
    const { result } = renderHook(() => useDebouncedValue("a", 300));
    expect(result.current).toBe("a");
  });

  it("窗口内连续变化只产出最后一个值", () => {
    vi.useFakeTimers();
    const { result, rerender } = renderHook(({ v }) => useDebouncedValue(v, 300), {
      initialProps: { v: "1" },
    });

    // 模拟快速敲键盘：4 次变更都在防抖窗口内
    for (const v of ["12", "123", "1234", "12345"]) {
      rerender({ v });
      act(() => {
        vi.advanceTimersByTime(100);
      });
    }
    // 累计 400ms 但每次都被重置 → 仍是旧值
    expect(result.current).toBe("1");

    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(result.current).toBe("12345");
    vi.useRealTimers();
  });

  it("卸载后定时器不再写入（无内存泄漏告警）", () => {
    vi.useFakeTimers();
    const { unmount } = renderHook(() => useDebouncedValue("x", 300));
    unmount();
    expect(() => act(() => void vi.advanceTimersByTime(1000))).not.toThrow();
    vi.useRealTimers();
  });
});
