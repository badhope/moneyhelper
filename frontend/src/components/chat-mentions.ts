/** 输入区 `@` 引用工作台文件：只做纯文本解析，便于单测。 */

export interface MentionSpan {
  /** `@` 在输入文本里的下标 */
  start: number;
  /** `@` 后面已输入的关键词，可为空 */
  query: string;
}

/** 从输入尾部识别 `@关键词`；只有行首或空白后的 `@` 才算提及。 */
export function mentionSpan(input: string): MentionSpan | null {
  const m = /(^|\s)@([^\s@]*)$/.exec(input);
  if (!m) return null;
  const at = input.lastIndexOf("@", input.length - 1);
  if (at < 0) return null;
  return { start: at, query: m[2] };
}

/** 删除提及触发词，保留 `@` 前面的空格语义。 */
export function stripMention(input: string, start: number): string {
  if (start < 0 || start >= input.length) return input;
  // 只清理位于输入尾部的完整提及；正文中间的 @ 不动。
  if (!/(^|\s)@([^\s@]*)$/.test(input)) return input;
  return input.slice(0, start).replace(/[ \t]+$/, "");
}

/** 文件名包含匹配，忽略大小写；最多返回 limit 条。 */
export function filterMentionFiles<T extends { filename: string }>(
  files: T[],
  query: string,
  limit = 6,
): T[] {
  const q = query.trim().toLowerCase();
  const hits = q ? files.filter((f) => f.filename.toLowerCase().includes(q)) : files;
  return hits.slice(0, Math.max(1, limit));
}
