import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

// Рендер Markdown в ответах ассистента: заголовки, списки, таблицы,
// жирный, ссылки, код. Стили — в styles.css (.md).
export default function Markdown({ children }) {
  return (
    <div className="md">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node, ...props }) => (
            <a target="_blank" rel="noreferrer" {...props} />
          ),
        }}
      >
        {children || ""}
      </ReactMarkdown>
    </div>
  );
}
