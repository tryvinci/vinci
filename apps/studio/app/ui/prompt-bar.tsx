import type { ReactNode } from "react";

/**
 * Floating composer. Image and Video pages can render their controls inside
 * this, or keep `.image-bar` — brand.css styles both from the same tokens.
 */
export function PromptBar({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <div className={className ? `prompt-bar ${className}` : "prompt-bar"}>{children}</div>;
}
