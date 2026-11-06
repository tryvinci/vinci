"use client";

import { useState, type ReactNode } from "react";

/** Collapsed rare options. Closed on first paint. */
export function AdvancedDisclosure({
  testId,
  children,
}: {
  testId: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="video-advanced">
      <button
        type="button"
        data-testid={testId}
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
      >
        Advanced
      </button>
      {open ? (
        <div className="video-advanced-fields" data-testid={`${testId}-fields`}>
          {children}
        </div>
      ) : null}
    </div>
  );
}