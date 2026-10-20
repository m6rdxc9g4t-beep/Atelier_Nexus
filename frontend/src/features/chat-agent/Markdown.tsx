import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

/** Réponse d'agent en Markdown (tableaux GFM). Aucun HTML brut n'est interprété. */
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn("prose-chat break-words", className)}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children: label }) => (
            <a href={href} target="_blank" rel="noopener noreferrer">
              {label}
            </a>
          ),
        }}
      >
        {children}
      </ReactMarkdown>
    </div>
  );
}
