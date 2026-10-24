import { type VariantProps, cva } from "class-variance-authority";

import { cn } from "@/lib/utils";

import { AgentIcon } from "./agentMeta";

/**
 * Tuile d'un agent : son icône dans un carré arrondi. `glass` reprend le verre néon de la tuile
 * de marque (en-tête, accueil, élément actif) ; `plain` reste discret (listes, avatars du fil).
 */
const tileVariants = cva("grid shrink-0 place-items-center", {
  variants: {
    size: {
      sm: "size-7 rounded-lg [&_svg]:size-3.5",
      md: "size-9 rounded-[10px] [&_svg]:size-[18px]",
      lg: "size-14 rounded-2xl [&_svg]:size-7",
    },
    variant: {
      glass: "atelier-brand__tile",
      plain: "border border-atelier-line bg-signature-faint text-accent-ink",
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
