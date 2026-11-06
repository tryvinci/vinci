import type { ReactNode } from "react";

/** Raised panel: cards, sheets, and menus share this surface. */
export function Surface({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={className ? `surface ${className}` : "surface"}>{children}</div>;
}
