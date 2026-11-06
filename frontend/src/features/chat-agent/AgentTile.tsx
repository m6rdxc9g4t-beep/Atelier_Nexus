import { type VariantProps, cva } from "class-variance-authority";

import { cn } from "@/lib/utils";

import { AgentIcon } from "./agentMeta";

/**
 * Icône d'un agent. Charte v2 : neutre, jamais dans la couleur de l'app (seule l'icône de la marque
 * porte la signature). `plain` : carré arrondi à trait fin (en-têtes, accueil, avatars du fil) ;
 * `bare` : l'icône seule, comme les entrées de navigation (barre latérale).
 */
const tileVariants = cva("grid shrink-0 place-items-center", {
  variants: {
    size: {
      sm: "size-6 rounded-sm [&_svg]:size-3.5",
      md: "size-8 rounded-md [&_svg]:size-4",
      lg: "size-12 rounded-lg [&_svg]:size-6",
    },
    variant: {
      plain: "border border-atelier-border bg-card text-muted-foreground",
      bare: "size-4 text-atelier-faint [&_svg]:size-4",
    },
  },
  defaultVariants: { size: "md", variant: "plain" },
});

export function AgentTile({
  icon,
  size,
  variant,
  className,
}: { icon?: string | null; className?: string } & VariantProps<typeof tileVariants>) {
  return (
    <span aria-hidden className={cn(tileVariants({ size, variant }), className)}>
      <AgentIcon icon={icon} />
    </span>
  );
}
