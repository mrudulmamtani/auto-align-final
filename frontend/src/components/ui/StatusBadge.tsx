"use client";

import { clsx } from "clsx";

const ratingColors: Record<string, string> = {
  critical: "bg-risk-critical/20 text-risk-critical border-risk-critical/40",
  high: "bg-risk-high/20 text-risk-high border-risk-high/40",
  medium: "bg-risk-medium/20 text-risk-medium border-risk-medium/40",
  low: "bg-risk-low/20 text-risk-low border-risk-low/40",
  informational: "bg-pwc-border/20 text-pwc-text-dim border-pwc-border/40",
};

export function StatusBadge({
  rating,
  className,
}: {
  rating: string;
  className?: string;
}) {
  const colors = ratingColors[(rating ?? "").toLowerCase()] ?? ratingColors.informational;
  return (
    <span
      className={clsx(
        "inline-block px-1.5 py-0.5 text-[10px] font-bold uppercase border rounded",
        colors,
        className
      )}
    >
      {rating}
    </span>
  );
}
