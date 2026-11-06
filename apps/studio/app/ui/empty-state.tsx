import type { ReactNode } from "react";

/** Centered empty offer: eyebrow, serif title, one line, actions. */
export function EmptyState({
  eyebrow,
  title,
  copy,
  actions,
  hint,
}: {
  eyebrow?: string;
  title: ReactNode;
  copy?: ReactNode;
  actions?: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className="empty-state">
      {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
      <h2>{title}</h2>
      {copy ? <p className="empty-state-copy">{copy}</p> : null}
      {actions ? <div className="empty-state-actions">{actions}</div> : null}
      {hint ? <p className="empty-state-hint">{hint}</p> : null}
    </div>
  );
}
