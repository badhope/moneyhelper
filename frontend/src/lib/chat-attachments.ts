/**
 * 聊天输入区的附件收口：粘贴、拖拽、文件选择都走同一套筛选。
 * 后端仍会校验文件头；这里只负责把明显不支持的格式挡在请求之前，
 * 避免用户拖进来一个 Word 后只看到一句英文 415。
 */
export const CHAT_ATTACHMENT_ACCEPT =
  ".txt,.md,.json,.csv,.log,.html,.htm,.png,.jpg,.jpeg,.webp,.gif,.pdf";

const ACCEPTED_EXT = /\.(txt|md|json|csv|log|html|htm|png|jpg|jpeg|webp|gif|pdf)$/i;

export interface AcceptedAttachmentFiles {
  accepted: File[];
  rejected: string[];
}

export function pickAttachmentFiles(files: File[]): AcceptedAttachmentFiles {
  const accepted: File[] = [];
  const rejected: string[] = [];
  for (const f of files) {
    if (ACCEPTED_EXT.test(f.name || "")) accepted.push(f);
    else rejected.push(f.name || "未命名文件");
  }
  return { accepted, rejected };
}

/** 只在拖拽里带文件时拦截浏览器默认「打开文件」行为。 */
export function hasFileDrag(types: readonly string[] | undefined): boolean {
  return Boolean(types?.includes("Files"));
}
