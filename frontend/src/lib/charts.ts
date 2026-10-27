/** ECharts 按需注册 + 轻量挂载 hook + 主题感知色板（运行时懒加载，echarts 不进首屏包）。
 *
 * 为什么自己写这 40 行而不用 echarts-for-react：该库已停更多年，且其 API 假设
 * echarts 同步 import（进首屏包 300KB+），而本项目需要运行时懒加载 + 按需注册
 * 图表模块（首屏不进 echarts）；现成的 use-echarts 等 hook 库同样不支持懒加载。
 * 故保留自实现——实例 init 一次、option 变化只 setOption、卸载 dispose。
 */

import { useEffect, useRef, useState, type RefObject } from "react";
import type { EChartsCoreOption, EChartsType } from "echarts/core";
import { useTheme } from "./theme";

type EChartsModule = typeof import("echarts/core");

let echartsModule: EChartsModule | null = null;
let loading: Promise<EChartsModule> | null = null;

/** 首次用到图表时才加载 echarts 运行时与所需图表/组件（副作用注册到同一 core），结果缓存复用。 */
function loadEcharts(): Promise<EChartsModule> {
  if (echartsModule) return Promise.resolve(echartsModule);
  if (!loading) {
    loading = (async () => {
      const core = await import("echarts/core");
      const [{ CanvasRenderer }] = await Promise.all([
        import("echarts/renderers"),
        import("echarts/lib/chart/bar"),
        import("echarts/lib/chart/line"),
        import("echarts/lib/chart/pie"),
        import("echarts/lib/chart/radar"),
        import("echarts/lib/chart/treemap"),
        import("echarts/lib/chart/graph"),
        import("echarts/lib/chart/candlestick"),
        import("echarts/lib/component/grid"),
        import("echarts/lib/component/legend"),
        import("echarts/lib/component/tooltip"),
        import("echarts/lib/component/radar"),
        import("echarts/lib/component/markLine"),
        import("echarts/lib/component/dataZoom"),
      ]);
      core.use([CanvasRenderer]);
      echartsModule = core;
      return core;
    })().catch((err) => {
      loading = null; // 失败后允许下次重试
      throw err;
    });
  }
  return loading;
}

/** 把 option 挂到容器上，容器尺寸变化自动 resize；echarts 运行时按需异步加载。
 *
 * 实例生命周期只跟容器走：挂载时 init 一次（不依赖 option 是否已就绪），卸载时 dispose。
 * option 后到或变化都只走 setOption，不重建实例（重建会丢动画并闪烁）。
 */
export function useEChart(
  ref: RefObject<HTMLDivElement | null>,
  option: EChartsCoreOption | null,
  deps: unknown[],
  onReady?: (chart: EChartsType) => void,
): void {
  const optionRef = useRef<EChartsCoreOption | null>(null);
  optionRef.current = option;
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  useEffect(() => {
    if (!ref.current) return;
    let disposed = false;
    let chart: EChartsType | null = null;
    let ro: ResizeObserver | null = null;
    loadEcharts()
      .then((core) => {
        const el = ref.current;
        if (disposed || !el) return;
        // 容器上已有实例就复用（避免 StrictMode 双挂载重复 init）
        chart = core.getInstanceByDom(el) ?? core.init(el);
        // echarts 异步加载期间 option 可能已经就绪，补一次避免首帧空白
        const latest = optionRef.current;
        if (latest) chart.setOption(latest, { notMerge: true });
        // 给调用方暴露实例（如缩放重置等交互），存在重复回调：覆盖式缓存最新
        onReadyRef.current?.(chart);
        // 容器初始尺寸可能为 0（在隐藏面板 / 懒加载 tab / flex 尚未布局时挂载）。
        // 此时 init 出来的实例宽高是 0，后续 resize() 不会重算坐标系，表现为「图表一片空白」。
        // 记录上次尺寸，仅在 0 → 非 0 或尺寸实际变化时先 resize 再重放 option。
        let lastW = el.clientWidth;
        let lastH = el.clientHeight;
        ro = new ResizeObserver(() => {
          const w = el.clientWidth;
          const h = el.clientHeight;
          if (w === lastW && h === lastH) return;
          const wasEmpty = lastW === 0 || lastH === 0;
          lastW = w;
          lastH = h;
          chart?.resize();
          if (wasEmpty && w > 0 && h > 0) {
            const cur = optionRef.current;
            if (cur) chart?.setOption(cur, { notMerge: true });
          }
        });
        ro.observe(el);
      })
      .catch((err: unknown) => {
        console.error("ECharts 加载失败", err);
      });
    return () => {
      disposed = true;
      ro?.disconnect();
      chart?.dispose();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 数据/配置变化：只 setOption，不重建实例。
  //
  // 关键：调用方常见写法是「数据没来 → return null；数据来了才渲染容器」。
  // 那种情况下挂载 effect 跑过一次、ref 是 null 就退出，之后再也不会初始化——
  // 图表的 div 有了，画布却永远是空的。这里在 ref 为空但容器已经出现时补一次 init。
  useEffect(() => {
    if (!option) return;
    loadEcharts()
      .then((core) => {
        const el = ref.current;
        if (!el) return;
        let inst = core.getInstanceByDom(el);
        if (!inst) {
          // 容器晚于首次挂载出现：补初始化
          inst = core.init(el);
          inst.setOption(option, { notMerge: true });
          return;
        }
        inst.resize();
        inst.setOption(option, { notMerge: true });
      })
      .catch(() => {
        /* 加载失败由挂载 effect 上报 */
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
}

/** 主题感知色板：浅色用深系、深色用亮系（与界面明暗一致）。
 * 模块级常量，引用身份稳定——放在 usePalette 里每次渲染新数组会让下游 memo 全部失效。 */
const PALETTE_DARK = [
  "#3ddad7", "#7ea6ff", "#52d68a", "#f2b549", "#b99aff",
  "#ff7aa2", "#5ad2f2", "#a8d84d", "#c58cff", "#8ea6c2",
];
const PALETTE_LIGHT = [
  "#0d7a66", "#2f6fed", "#16a34a", "#d97706", "#7c5cd6",
  "#e11d48", "#0891b2", "#65a30d", "#9333ea", "#64748b",
];

export function usePalette(): string[] {
  const { resolved } = useTheme();
  return resolved === "dark" ? PALETTE_DARK : PALETTE_LIGHT;
}

/** 通用文本色（随明暗） */
export function axisLabelColor(resolved: "light" | "dark"): string {
  return resolved === "dark" ? "#9fb0c9" : "#64748b";
}

/** 金融涨跌色：跟随全局颜色方案（A股红涨绿跌默认，可切 us 绿涨红跌）。
 *
 * 返回 { up, down }，通过解析 --color-up / --color-down CSS 变量获得；
 * 并用 MutationObserver 监听 data-scheme / class / data-theme 变化触发重算，
 * 保证 K 线蜡烛、成交量等金融图表在切换颜色方案时即时换色。
 */
export function useCandleColors(): { up: string; down: string } {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const root = document.documentElement;
    const mo = new MutationObserver(() => setTick((v) => v + 1));
    mo.observe(root, { attributes: true, attributeFilter: ["data-scheme", "class", "data-theme"] });
    return () => mo.disconnect();
  }, []);

  // tick 参与读取：每次颜色方案变化都重新解析
  void tick;
  const style = getComputedStyle(document.documentElement);
  const up = style.getPropertyValue("--color-up").trim() || "#dc2626";
  const down = style.getPropertyValue("--color-down").trim() || "#059669";
  return { up, down };
}
