"use client";

import { useCallback, useEffect, useState } from "react";
import { money } from "../lib/model-capabilities";
import { approvalReason, plainError } from "./ui/plain-text";

/** A run that waits for approval, as GET /runs gives it. */
type WaitingRun = {
  id: string;
  state?: string;
  skill?: string;
  error?: unknown;
  inputs?: { prompt?: unknown };
  estimate?: { total?: number };
  awaiting_reason?: unknown;
};

/** Fired with a run id when a Studio run stops at `awaiting_approval`: the Studio opens `#cost/<id>`. */
export const AWAITING_EVENT = "vinci-run-awaiting";

/**
 * Runs over `max_cost`, the monthly cap or `require_approval_over`, with their price, reason and
 * Approve and Cancel buttons (COREPRODUC-786). Before, only `vinci jobs approve <run_id>` could
 * start them. An agent cannot approve here: only the person in the Studio can.
 *
 * Args:
 *   api: The Studio's fetch helper (throws on a non-2xx answer).
 *   focus: The run a link names (`#cost/<run_id>`), outlined in the list.
 *   onChange: Called after Approve or Cancel, so the feed reloads.
 */
export function ApprovalList({
  api,
  focus,
  onChange,
}: {
  api: <T>(path: string, opts?: RequestInit) => Promise<T>;
  focus: string;
  onChange: () => void;
}) {
  const [rows, setRows] = useState<WaitingRun[] | null>(null);
  const [line, setLine] = useState("");
  const load = useCallback(async () => {
    // Every project's runs: an agent's run has no Studio project (the default one).
    const body = await api<{ runs: WaitingRun[] }>("/runs");
    setRows((body.runs || []).filter((run) => run.state === "awaiting_approval"));
  }, [api]);
  useEffect(() => {
    load().catch((err) => setLine(plainError(err)));
  }, [load, focus]);

  async function act(run: WaitingRun, verb: "approve" | "cancel") {
    console.info("[studio] approval", { run: run.id, verb, total: run.estimate?.total });
    setLine(verb === "approve" ? "Starting the run…" : "Cancelling…");
    try {
      const done = await api<WaitingRun>(`/runs/${encodeURIComponent(run.id)}/${verb}`, { method: "POST" });
      setLine(
        verb === "cancel"
          ? "Cancelled. Nothing was spent."
          : done.state === "failed"
            ? plainError(typeof done.error === "string" ? done.error : "")
            : done.state === "completed"
              ? "Approved. Your file is ready."
              : "Approved. The run started.",
      );
      onChange();
    } catch (err) {
      console.warn("[studio] approval failed", { run: run.id, verb, err: String(err) });
      setLine(plainError(err));
    }
    await load().catch((err) => setLine(plainError(err)));
  }

  const missing = Boolean(focus && rows && !line && !rows.some((run) => run.id === focus));
  return (
    <section className="approvals" data-testid="approvals">
      <h3>Waiting for your approval</h3>
      {rows === null ? <p className="muted">Loading…</p> : null}
      {rows?.length === 0 ? <p className="muted">No runs wait for your approval.</p> : null}
      {missing ? <p className="muted">Run {focus} does not wait for approval now.</p> : null}
      {rows?.map((run) => (
        <div
          className={"hit approval" + (run.id === focus ? " on" : "")}
          key={run.id}
          data-run={run.id}
          ref={run.id === focus ? (el) => el?.scrollIntoView({ block: "nearest" }) : undefined}
        >
          <strong>{typeof run.inputs?.prompt === "string" && run.inputs.prompt ? run.inputs.prompt : run.skill || run.id}</strong>
          <div className="muted">{approvalReason(run)}</div>
          <div className="approval-actions">
            <button type="button" className="run" onClick={() => void act(run, "approve")}>
              Approve {money(run.estimate?.total)}
            </button>
            <button type="button" className="ghost" onClick={() => void act(run, "cancel")}>
              Cancel
            </button>
          </div>
        </div>
      ))}
      {line ? <p className="log" role="status">{line}</p> : null}
    </section>
  );
}
