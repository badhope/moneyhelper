import { describe, expect, it } from "vitest";
import { hasFileDrag, pickAttachmentFiles } from "./chat-attachments";

const file = (name: string) => new File(["x"], name, { type: "application/octet-stream" });

describe("聊天附件筛选", () => {
  it("放行文本、CSV、图片与 PDF", () => {
    const picked = pickAttachmentFiles([
      file("a.md"),
      file("b.csv"),
      file("c.PNG"),
      file("d.pdf"),
    ]);
    expect(picked.accepted.map((f) => f.name)).toEqual(["a.md", "b.csv", "c.PNG", "d.pdf"]);
    expect(picked.rejected).toEqual([]);
  });

  it("挡下 Word、压缩包和没有扩展名的文件", () => {
    const picked = pickAttachmentFiles([file("方案.docx"), file("归档.zip"), file("README")]);
    expect(picked.accepted).toEqual([]);
    expect(picked.rejected).toEqual(["方案.docx", "归档.zip", "README"]);
  });

  it("空文件名不会误判成支持格式", () => {
    expect(pickAttachmentFiles([file("")]).rejected).toEqual(["未命名文件"]);
  });
});

describe("hasFileDrag", () => {
  it("只认 Files 类型", () => {
    expect(hasFileDrag(["Files", "text/plain"])).toBe(true);
    expect(hasFileDrag(["text/plain"])).toBe(false);
    expect(hasFileDrag(undefined)).toBe(false);
  });
});
