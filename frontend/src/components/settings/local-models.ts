/** 本地推理端与精选小模型清单（纯数据）。
 *
 * 只收 OpenAI 兼容、能在普通笔记本 8–16GB 内存跑起来的一档：
 * Ollama / LM Studio / llama.cpp / vLLM。下载链接给到官方发布页或模型库，
 * 不在应用内代下大文件，也不伪造“已安装”状态。
 */

export type EngineId = "ollama" | "lmstudio" | "llamacpp" | "vllm";

export interface LocalEngine {
  id: EngineId;
  name: string;
  base: string;
  /** 各端默认模型：点“填入”时一并写进 ai_model */
  defaultModel: string;
  installUrl: string;
  installLabel: { zh: string; en: string };
  note: { zh: string; en: string };
}

export const LOCAL_ENGINES: LocalEngine[] = [
  {
    id: "ollama",
    name: "Ollama",
    base: "http://127.0.0.1:11434/v1",
    defaultModel: "qwen3:4b-instruct-2507",
    installUrl: "https://ollama.com/download",
    installLabel: { zh: "安装 Ollama", en: "Install Ollama" },
    note: {
      zh: "装完直接 ollama pull 模型；OpenAI 兼容端点在 11434。",
      en: "Install, pull a model, and use the OpenAI-compatible endpoint on 11434.",
    },
  },
  {
    id: "lmstudio",
    name: "LM Studio",
    base: "http://127.0.0.1:1234/v1",
    defaultModel: "Qwen3-4B-Instruct-2507",
    installUrl: "https://lmstudio.ai/models",
    installLabel: { zh: "打开模型库", en: "Open model library" },
    note: {
      zh: "图形界面下载 GGUF/MLX；启动 Local Server 后端口默认 1234。",
      en: "Download GGUF/MLX in the app; the local server defaults to port 1234.",
    },
  },
  {
    id: "llamacpp",
    name: "llama.cpp",
    base: "http://127.0.0.1:8090/v1",
    defaultModel: "MiniCPM5-2B",
    installUrl: "https://github.com/ggml-org/llama.cpp/releases",
    installLabel: { zh: "下载 llama.cpp", en: "Download llama.cpp" },
    note: {
      zh: "最轻的 CPU 路线；llama-server 加 --jinja -fa on 启动。",
      en: "Lightest CPU path; start llama-server with --jinja -fa on.",
    },
  },
  {
    id: "vllm",
    name: "vLLM",
    base: "http://127.0.0.1:8000/v1",
    defaultModel: "Qwen/Qwen3-4B-Instruct-2507",
    installUrl: "https://docs.vllm.ai/en/latest/getting_started/installation.html",
    installLabel: { zh: "安装 vLLM", en: "Install vLLM" },
    note: {
      zh: "适合有独显的机器；吞吐高，启动比前三个重。",
      en: "For machines with a GPU; high throughput, heavier startup.",
    },
  },
];

export interface LocalModel {
  id: string;
  name: string;
  params: string;
  size: string;
  note: { zh: string; en: string };
  downloadUrl: string;
  /** 各推理端对应的模型名；点“填入”时按当前端取 */
  endpoints: Record<EngineId, string>;
}

export const LOCAL_MODELS: LocalModel[] = [
  {
    id: "minicpm5-2b",
    name: "MiniCPM5 2B",
    params: "2B",
    size: "Q4 · 约 1.4GB",
    note: {
      zh: "端侧小模型，项目已用 llama.cpp 实测过工具调用；低配 CPU 也能跑。",
      en: "On-device 2B model; tool calls verified with llama.cpp here, runs on low-end CPUs.",
    },
    downloadUrl: "https://openbmb.cn/docs/guides/minicpm-text/minicpm5-2b",
    endpoints: {
      ollama: "maternion/minicpm5:2b",
      lmstudio: "MiniCPM5-2B-GGUF",
      llamacpp: "MiniCPM5-2B-Q4_K_M.gguf",
      vllm: "openbmb/MiniCPM5-2B",
    },
  },
  {
    id: "qwen3-4b",
    name: "Qwen3 4B Instruct",
    params: "4B",
    size: "Q4 · 约 2.6GB",
    note: {
      zh: "4B 档综合最稳，中文与工具调用兼顾；内存建议 8GB 以上。",
      en: "The most balanced 4B option for Chinese and tool calls; 8GB+ RAM recommended.",
    },
    downloadUrl: "https://ollama.com/library/qwen3",
    endpoints: {
      ollama: "qwen3:4b-instruct-2507",
      lmstudio: "Qwen3-4B-Instruct-2507",
      llamacpp: "Qwen3-4B-Instruct-2507-UD-Q4_K_XL.gguf",
      vllm: "Qwen/Qwen3-4B-Instruct-2507",
    },
  },
  {
    id: "gemma3-4b",
    name: "Gemma 3 4B",
    params: "4B",
    size: "Q4 · 约 2.5GB",
    note: {
      zh: "英文问答与本地摘要稳；中文能力一般，适合双语场景。",
      en: "Solid English Q&A and local summarization; Chinese is weaker, good for bilingual use.",
    },
    downloadUrl: "https://ollama.com/library/gemma3",
    endpoints: {
      ollama: "gemma3:4b",
      lmstudio: "gemma-3-4b-it",
      llamacpp: "gemma-3-4b-it-Q4_K_M.gguf",
      vllm: "google/gemma-3-4b-it",
    },
  },
  {
    id: "llama32-3b",
    name: "Llama 3.2 3B",
    params: "3B",
    size: "Q4 · 约 2.0GB",
    note: {
      zh: "轻量、英文长上下文稳；中文和财务术语弱于 Qwen。",
      en: "Lightweight with stable English long context; weaker Chinese and finance terms than Qwen.",
    },
    downloadUrl: "https://ollama.com/library/llama3.2",
    endpoints: {
      ollama: "llama3.2:3b",
      lmstudio: "Llama-3.2-3B-Instruct",
      llamacpp: "Llama-3.2-3B-Instruct-Q4_K_M.gguf",
      vllm: "meta-llama/Llama-3.2-3B-Instruct",
    },
  },
];
