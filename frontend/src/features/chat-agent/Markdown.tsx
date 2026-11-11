import { memo } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";

import { cn } from "@/lib/utils";

const PLUGINS = [remarkGfm];

const COMPONENTS: Components = {
  a: ({ href, children: label }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {label}
    </a>
  ),
};

/**
 * Réponse d'agent en Markdown (tableaux GFM). Aucun HTML brut n'est interprété.
 * Mémoïsé sur son texte : pendant qu'une réponse arrive, chaque fragment re-rend le fil, et sans
 * cela toutes les réponses déjà affichées étaient analysées de nouveau à chaque fragment.
 */
export const Markdown = memo(function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={cn("prose-chat break-words", className)}>
      <ReactMarkdown remarkPlugins={PLUGINS} components={COMPONENTS}>
        {children}
      </ReactMarkdown>
    </div>
  );
});
