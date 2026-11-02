/** 语音播报（M5.4）：浏览器原生 speechSynthesis，零依赖、离线可用。
 *
 * 设计取舍：
 * - 不接云 TTS：会把回答全文发给第三方，且要额外密钥；浏览器内置语音已覆盖中英。
 * - 只播报「最终答案」，不播报流式增量（逐字读会像结巴）。
 * - 显式开关：settings.voice_output = on/off，默认 off；播报按钮也常驻，用户可单次触发。
 * - 长文截断：超过 1200 字只读前 1200 字并提示，避免长时间朗读无法停止。
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

const MAX_SPEAK_CHARS = 1200;

export interface SpeakState {
  supported: boolean;
  speaking: boolean;
  speak: (text: string, lang?: "zh" | "en") => void;
  stop: () => void;
  toggle: (text: string, lang?: "zh" | "en") => void;
  truncated: boolean;
}

function pickVoice(lang: "zh" | "en"): SpeechSynthesisVoice | null {
  if (typeof window === "undefined" || !window.speechSynthesis) return null;
  const voices = window.speechSynthesis.getVoices();
  const prefix = lang === "zh" ? "zh" : "en";
  return (
    voices.find((v) => v.lang.toLowerCase().startsWith(prefix) && v.localService) ??
    voices.find((v) => v.lang.toLowerCase().startsWith(prefix)) ??
    null
  );
}

export function useSpeech(): SpeakState {
  const supported = typeof window !== "undefined" && typeof window.speechSynthesis !== "undefined";
  const [speaking, setSpeaking] = useState(false);
  const [truncated, setTruncated] = useState(false);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);

  const stop = useCallback(() => {
    if (!supported) return;
    window.speechSynthesis.cancel();
    setSpeaking(false);
  }, [supported]);

  const speak = useCallback(
    (text: string, lang: "zh" | "en" = "zh") => {
      if (!supported) return;
      const plain = (text || "")
        .replace(/```[\s\S]*?```/g, "（代码块略）")
        .replace(/[#*_>`]/g, "")
        .replace(/\s+/g, " ")
        .trim();
      if (!plain) return;
      const over = plain.length > MAX_SPEAK_CHARS;
      setTruncated(over);
      const body = over ? `${plain.slice(0, MAX_SPEAK_CHARS)}…（内容较长，已截断）` : plain;

      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(body);
      u.lang = lang === "zh" ? "zh-CN" : "en-US";
      u.rate = lang === "zh" ? 1.0 : 1.05;
      u.pitch = 1;
      const voice = pickVoice(lang);
      if (voice) u.voice = voice;
      u.onend = () => setSpeaking(false);
      u.onerror = () => setSpeaking(false);
      utteranceRef.current = u;
      setSpeaking(true);
      window.speechSynthesis.speak(u);
    },
    [supported],
  );

  const toggle = useCallback(
    (text: string, lang: "zh" | "en" = "zh") => {
      if (speaking) stop();
      else speak(text, lang);
    },
    [speaking, speak, stop],
  );

  useEffect(() => {
    if (!supported) return;
    // 页面卸载/切换会话时停止朗读，避免后台残留
    return () => {
      window.speechSynthesis.cancel();
    };
  }, [supported]);

  return useMemo(
    () => ({ supported, speaking, speak, stop, toggle, truncated }),
    [supported, speaking, speak, stop, toggle, truncated],
  );
}
