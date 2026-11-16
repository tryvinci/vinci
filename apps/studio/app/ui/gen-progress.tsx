"use client";

import { useEffect, useState } from "react";
import { fakeProgress, progressLabel, type RunClock } from "../../lib/progress";

/**
 * A generation's progress bar: fills to 90% over the model's average time, counting down, then
 * waits at 90% with "Almost done…" until the run ends (COREPRODUC-659; `lib/progress.ts`).
 *
 * Args:
 *   clock: When the run started and the seconds it should take.
 *   compact: A thin bar and a short line, for a canvas node.
 */
export function GenProgress({ clock, compact, testId }: { clock: RunClock; compact?: boolean; testId?: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const tick = window.setInterval(() => setNow(Date.now()), 250);
    return () => window.clearInterval(tick);
  }, []);
  const { pct, left } = fakeProgress(now - clock.startedAt, clock.seconds);
  return (
    <div className={"gen-progress" + (compact ? " compact" : "")} data-testid={testId}>
      <div
        className="gen-progress-track"
        role="progressbar"
        aria-label="Generating"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
        aria-valuetext={progressLabel(left)}
      >
        <div className="gen-progress-fill" style={{ width: `${pct}%` }} />
      </div>
      <span className="gen-progress-label">{progressLabel(left)}</span>
    </div>
  );
}
