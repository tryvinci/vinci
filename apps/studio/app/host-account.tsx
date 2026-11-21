"use client";

import { useCallback, useEffect, useState } from "react";
import { money } from "../lib/model-capabilities";

/**
 * Credits on a host such as Vinci Platform (`account` in `doctor.host.pages`, COREPRODUC-747).
 *
 * The host sends the balance and the newest credit moves (`GET /account`): what each run burned and
 * what was added. `host.credits_contact` (a `mailto:` or a page) is where a person asks for more
 * credits. The Studio has no payment code; the host owns the ledger.
 */

type Usage = { id: string; at: string; title: string; detail?: string; credits: number };
type AccountReply = { balance: number; currency?: string; usage?: Usage[] };

/** A date from the host as "Nov 21, 2026"; "" when it is not a date. */
function day(value?: string | null): string {
  const at = value ? new Date(value) : null;
  return at && !Number.isNaN(at.getTime()) ? at.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" }) : "";
}

export function HostAccount({ hostName, contact }: { hostName: string; contact?: string }) {
  const [reply, setReply] = useState<AccountReply | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    setError("");
    setReply(null);
    fetch("/vinci-api/account")
      .then(async (res) => {
        const body = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(String(body.detail || `Credits are not available (HTTP ${res.status}).`));
        return body as AccountReply;
      })
      .then((body) => {
        console.info("[credits] account", { balance: body.balance, usage: body.usage?.length });
        setReply(body);
      })
      .catch((err: Error) => {
        console.warn("[credits] account failed", err.message);
        setError(err.message || "Could not reach the host.");
      });
  }, []);
  useEffect(load, [load]);

  const usage = reply?.usage || [];
  return (
    <div className="keys connect host-keys host-account" data-testid="host-account">
      <p className="eyebrow">{hostName}</p>
      <h2>Credits</h2>
      <p className="muted lede">
        Runs on {hostName}&apos;s models use credits. Runs on your own provider account (Connect) use none.
      </p>
      {error ? (
        <>
          <p className="log error" role="alert" data-testid="host-account-error">{error}</p>
          <div className="file-row">
            <button className="ghost" type="button" onClick={load}>Try again</button>
          </div>
        </>
      ) : !reply ? (
        <p className="muted" role="status">Loading your credits…</p>
      ) : (
        <>
          <div className="connect-sheet" data-testid="host-account-balance">
            <span className="kind">Balance</span>
            <strong className="account-balance">{money(reply.balance, reply.currency || "credits")}</strong>
            {reply.balance <= 0 ? <p className="log error">You have no credits left.</p> : null}
            {contact ? (
              <p className="muted" data-testid="host-account-contact">
                Need more credits?{" "}
                <a href={contact} target="_top" rel="noreferrer">
                  Contact us
                </a>
              </p>
            ) : null}
          </div>
          <h3 className="account-head">Usage</h3>
          {usage.length ? (
            <ul className="account-usage" data-testid="host-account-usage">
              {usage.map((row) => (
                <li key={row.id}>
                  <span className="account-when">{day(row.at)}</span>
                  <span className="account-what">
                    {row.title}
                    {row.detail ? <small>{row.detail}</small> : null}
                  </span>
                  <span className={row.credits > 0 ? "account-delta plus" : "account-delta"}>
                    {row.credits > 0 ? "+" : ""}
                    {money(row.credits, "credits")}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="muted" data-testid="host-account-usage-empty">No credit use yet. Your runs show here.</p>
          )}
        </>
      )}
    </div>
  );
}
