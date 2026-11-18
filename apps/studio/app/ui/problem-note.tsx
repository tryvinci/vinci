"use client";

import type { RunAction, RunProblem } from "./plain-text";

const LABEL: Record<RunAction, string> = { credits: "Add credits", upgrade: "Upgrade", connect: "Open Connect" };

/**
 * A refused or failed run in red, with the one button that fixes it (COREPRODUC-692). Bug fixed
 * (first occurrence 2026-11-18, user report): the reason showed only as dim text in the top bar, so
 * a run that had no credits, or that a provider refused, seemed to stop with no warning.
 *
 * Args:
 *   problem: The reason and the action (`runProblem`).
 *   onAction: Runs the action (opens Credits or Connect). Without it, no button.
 *   className: `run-hint` above Generate, `image-card-problem` in a feed card.
 *   testId: For tests.
 */
export function ProblemNote({
  problem,
  onAction,
  className = "",
  testId,
}: {
  problem: RunProblem;
  onAction?: (action: RunAction) => void;
  className?: string;
  testId?: string;
}) {
  const action = problem.action;
  return (
    <div className={`run-problem ${className}`} role="alert" data-testid={testId}>
      <span>{problem.text}</span>
      {action && onAction ? (
        <button type="button" className="ghost run-problem-action" onClick={() => onAction(action)}>
          {LABEL[action]}
        </button>
      ) : null}
    </div>
  );
}
