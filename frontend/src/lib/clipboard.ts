import copy from "copy-to-clipboard";

/**
 * 复制文本，返回是否成功。
 *
 * navigator.clipboard 只在安全上下文（HTTPS/localhost）可用；手机通过局域网
 * http://192.168.x.x 访问时会被浏览器禁用。copy-to-clipboard 会自动回退到
 * execCommand，避免「提示已复制但实际没复制」。
 */
export function copyText(text: string): boolean {
  try {
    return copy(text);
  } catch {
    return false;
  }
}
