import { useCallback, useEffect, useRef, useState } from "react";

/**
 * 可拖拽宽度（桌面侧栏 / 数据面板共用）。
 *
 * 设计取舍：
 * - 宽度存 localStorage，刷新后保持；首次用 defaultWidth
 * - 用 pointer events 而不是 mouse events：触控屏/触控笔同样可用
 * - 拖动时锁 body cursor 与 user-select，避免选中文字、光标闪烁
 * - 双击分隔条恢复默认宽度（比"去设置里改"更符合直觉）
 * - 宽度夹在 [min, max]，并用容器宽度算出上限，防止把主区域挤没
 */
export function useResizableWidth({
  storageKey,
  defaultWidth,
  min = 200,
  max = 420,
  direction = "left",
}: {
  storageKey: string;
  defaultWidth: number;
  min?: number;
  max?: number;
  /** 右侧栏拖左边缘时，鼠标左移应让栏变宽，方向与左侧栏相反。 */
  direction?: "left" | "right";
}) {
  const [width, setWidth] = useState<number>(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      const n = raw ? Number(raw) : NaN;
      return Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : defaultWidth;
    } catch {
      return defaultWidth;
    }
  });
  const [dragging, setDragging] = useState(false);
  const startRef = useRef<{ x: number; w: number } | null>(null);

  const clamp = useCallback(
    (n: number) => Math.min(max, Math.max(min, n)),
    [min, max],
  );

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, String(width));
    } catch {
      /* 隐私模式下 localStorage 可能不可写，忽略 */
    }
  }, [storageKey, width]);

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (e.button !== 0) return;
      e.preventDefault();
      (e.target as HTMLElement).setPointerCapture?.(e.pointerId);
      startRef.current = { x: e.clientX, w: width };
      setDragging(true);
    },
    [width],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      const start = startRef.current;
      if (!start) return;
      const delta = direction === "left" ? e.clientX - start.x : start.x - e.clientX;
      setWidth(clamp(start.w + delta));
    },
    [clamp, direction],
  );

  const endDrag = useCallback(() => {
    startRef.current = null;
    setDragging(false);
  }, []);

  const reset = useCallback(() => setWidth(defaultWidth), [defaultWidth]);

  useEffect(() => {
    if (!dragging) return;
    const prevCursor = document.body.style.cursor;
    const prevSelect = document.body.style.userSelect;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    return () => {
      document.body.style.cursor = prevCursor;
      document.body.style.userSelect = prevSelect;
    };
  }, [dragging]);

  return {
    width,
    dragging,
    min,
    max,
    setWidth: (n: number) => setWidth(clamp(n)),
    reset,
    handleProps: {
      onPointerDown,
      onPointerMove,
      onPointerUp: endDrag,
      onPointerCancel: endDrag,
      onDoubleClick: reset,
    },
  };
}
