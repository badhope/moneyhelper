import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSanitize from "rehype-sanitize";

/** 工作台里的 Markdown 预览：只读、走与回答同一套 sanitize。 */
export function MarkdownPreview({ text }: { text: string }) {
  return (
    <div className="md-body text-[13.5px] leading-relaxed text-foreground/90">
      <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeSanitize]}>
        {text}
      </ReactMarkdown>
    </div>
  );
}
