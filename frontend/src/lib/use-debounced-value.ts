/** 输入防抖：返回延迟 delay 毫秒后才更新的值。
 *
 * 用途：搜索框与数字输入框。真实成本不是 setState 本身，而是它触发的
 * 网络请求——每敲一个字符发一次请求，既浪费请求也让结果闪烁（后到的
 * 旧响应会覆盖新响应）。
 *
 * 与 useDeferredValue 的差别：deferredValue 只在渲染竞争时让步，
 * 不会减少请求次数；这里要的是「停止输入才发请求」，所以必须是定时器。
 */
import { useEffect, useState } from "react";

export function useDebouncedValue<T>(value: T, delay = 300): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), delay);
    return () => window.clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}
