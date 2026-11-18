"use client";

import { useEffect, useState } from "react";
import { money } from "../lib/model-capabilities";

/**
 * Connect on a host such as Vinci Platform: the user's own provider accounts (`doctor.host.keys`).
 * Wavespeed takes a pasted API key (COREPRODUC-613); Higgsfield and Magnific sign in with the
 * user's account (MCP OAuth, COREPRODUC-614). A run on the user's account costs no host credits,
 * because the provider bills the user. The host stores keys and sign-ins encrypted and shows only
 * the last 4 characters of a key.
 */

type KeyRow = {
  configured?: boolean;
  available?: boolean;
  display_name?: string;
  key_hint?: string;
  auth_state?: string;
};

const NAMES: Record<string, string> = {
  vinci: "Vinci",
  wavespeed: "Wavespeed",
  mcp_higgsfield: "Higgsfield",
  mcp_magnific: "Magnific",
};

/** A provider's name for menus ("mcp_higgsfield" → "Higgsfield"); other ids stay as they are. */
export function providerName(id = ""): string {
  return NAMES[id] || id;
}
const NOTES: Record<string, string> = {
  wavespeed: "The Studio's models run on your key and show its dollar price.",
  mcp_higgsfield:
    "Adds Higgsfield models. They run on your Higgsfield credits.",
  mcp_magnific: "Adds Magnific models. They run on your Magnific credits.",
};

/** Where to get a key or read the provider's docs (COREPRODUC-650 shell-15: Connect had no link). */
const LINKS: Record<string, [string, string]> = {
  wavespeed: ["Get a Wavespeed key", "https://wavespeed.ai/accesskey"],
  mcp_higgsfield: ["Higgsfield docs", "https://docs.higgsfield.ai"],
  mcp_magnific: ["Magnific docs", "https://docs.magnific.com/introduction"],
};

/** The provider's link, under its note. */
function ProviderLink({ id }: { id: string }) {
  const link = LINKS[id];
  return link ? (
    <p className="muted">
      <a href={link[1]} target="_blank" rel="noreferrer">
        {link[0]}
      </a>
    </p>
  ) : null;
}

type BalanceReply = { amount?: number | null; currency?: string; error?: string };

/**
 * What the user's own account can spend now: `GET /providers/{id}/balance` (free provider calls).
 * Added 2026-11-15: a Higgsfield card said "Signed in" while every run failed, and nobody could see
 * whether the account was out of credits. It loads again when the sign-in or the key changes.
 *
 * Args (props):
 *   id: The provider id (`wavespeed`, `mcp_higgsfield`, `mcp_magnific`).
 *   version: Changes when the sign-in state or the key changes, so the balance loads again.
 */
function Balance({ id, version }: { id: string; version: string }) {
  const [reply, setReply] = useState<BalanceReply | null>(null);
  useEffect(() => {
    let live = true;
    setReply(null);
    fetch(`/vinci-api/providers/${id}/balance`)
      .then(async (res) => (res.ok ? res.json() : { error: `Balance not available (HTTP ${res.status}).` }))
      .catch(() => ({ error: "Could not reach Vinci for the balance." }))
      .then((body: BalanceReply) => {
        if (!live) return;
        console.info("[connect] balance", { id, amount: body.amount, currency: body.currency, error: body.error });
        setReply(body);
      });
    return () => {
      live = false;
    };
  }, [id, version]);
  if (!reply) return <div className="muted" data-testid={`balance-${id}`}>Balance: loading…</div>;
  if (reply.error || reply.amount == null)
    return <div className="log error" role="alert" data-testid={`balance-${id}`}>{reply.error || "The provider sent no balance."}</div>;
  const empty = reply.amount <= 0;
  return (
    <div className={empty ? "log error" : "muted"} data-testid={`balance-${id}`}>
      Balance: {money(reply.amount, reply.currency)}
      {empty ? ". Add credits on the provider's site before you run." : ""}
    </div>
  );
}

/** A Connect result on one card: the text, whether it failed, and the sign-in page while a sign-in waits. */
export type HostNote = { text: string; error?: boolean; url?: string };

/** The status line of a sign-in card. */
function signInState(row?: KeyRow): string {
  if (row?.auth_state === "connected") return "Signed in";
  if (row?.auth_state === "needs_reconnect") return "Sign in again";
  return "Not signed in";
}

export function HostKeys(props: {
  hostName: string;
  keys: string[];
  providers: Record<string, KeyRow>;
  draft: Record<string, string>;
  setDraft: (
    update: (d: Record<string, string>) => Record<string, string>,
  ) => void;
  onSave: (id: string) => void;
  onRemove: (id: string) => void;
  onSignIn: (id: string) => void;
  /** The last result per provider: it shows on that provider's card (it was under the list, out of view). */
  notes: Record<string, HostNote>;
  /** The action in flight per provider ("in" or "out"): its card shows it and takes no clicks. */
  pending: Record<string, "in" | "out">;
}) {
  const { draft, setDraft } = props;
  /**
   * A card's feedback. The polite status region stays mounted, so a screen reader hears the progress
   * and the result; a failure mounts an alert instead.
   */
  const cardNote = (id: string, progress: string) => {
    const n = props.notes[id];
    return (
      <>
        {/* Progress is for screen readers only: the busy button already shows it. */}
        <p className={progress ? "sr-only" : "log"} role="status" data-testid="host-keys-log">
          {progress || (n && !n.error ? n.text : null)}
          {n?.url && !progress ? (
            <>
              {" "}
              <a href={n.url} target="_blank" rel="noreferrer">
                Open the sign-in page
              </a>
            </>
          ) : null}
        </p>
        {n?.error ? (
          <p className="log error" role="alert" data-testid="host-keys-error">
            {n.text}
          </p>
        ) : null}
      </>
    );
  };
  return (
    <div className="keys connect host-keys" data-testid="host-keys">
      <p className="eyebrow">{props.hostName}</p>
      <h2>Your accounts</h2>
      <p className="muted lede">
        Run models on your own provider account: paste a Wavespeed key, or sign
        in to Higgsfield or Magnific. Runs on your account cost no credits: the
        provider bills you. Keys and sign-ins are stored encrypted, and this
        page shows only the last 4 characters of a key.
      </p>
      <div className="host-key-list">
        {props.keys.map((id) => {
          const row = props.providers[id];
          const name = row?.display_name || NAMES[id] || id;
          const busy = Boolean(props.pending[id]);
          const out = props.pending[id] === "out";
          if (id.startsWith("mcp_")) {
            const signedIn = row?.auth_state === "connected";
            return (
              <div className="connect-sheet" key={id} data-host-key={id}>
                <span className="kind">Sign-in</span>
                <strong>{name}</strong>
                <div className="muted">{signInState(row)}</div>
                {signedIn ? <Balance id={id} version={row?.auth_state || ""} /> : null}
                <p className="muted">{NOTES[id] || ""}</p>
                <ProviderLink id={id} />
                <div className="file-row">
                  {row?.configured ? (
                    <button
                      className="ghost"
                      type="button"
                      disabled={busy}
                      aria-busy={out}
                      onClick={() => props.onRemove(id)}
                    >
                      {out ? "Signing out…" : "Sign out"}
                    </button>
                  ) : null}
                  {signedIn ? null : (
                    <button
                      className="run"
                      type="button"
                      disabled={busy}
                      aria-busy={busy && !out}
                      onClick={() => props.onSignIn(id)}
                    >
                      {busy && !out ? "Opening sign-in…" : `Sign in to ${name}`}
                    </button>
                  )}
                </div>
                {cardNote(id, busy ? (out ? "Signing out…" : "Opening sign-in…") : "")}
              </div>
            );
          }
          const ready = Boolean(row?.configured);
          const missing = !(draft[`key-${id}`] || "").trim();
          return (
            <div className="connect-sheet" key={id} data-host-key={id}>
              <span className="kind">Provider</span>
              <strong>{name}</strong>
              <div className="muted">
                {ready
                  ? `On your key ${row?.key_hint || ""}`.trim()
                  : "Not connected"}
              </div>
              {ready ? <Balance id={id} version={row?.key_hint || ""} /> : null}
              <p className="muted">{NOTES[id] || ""}</p>
              <ProviderLink id={id} />
              <label htmlFor={`key-${id}`}>
                {ready ? "Paste a new key" : "Paste key"}
              </label>
              <input
                id={`key-${id}`}
                type="password"
                autoComplete="new-password"
                value={draft[`key-${id}`] || ""}
                onChange={(ev) =>
                  setDraft((d) => ({ ...d, [`key-${id}`]: ev.target.value }))
                }
                placeholder={`${name} API key`}
              />
              <div className="file-row">
                {ready ? (
                  <button
                    className="ghost"
                    type="button"
                    disabled={busy}
                    aria-busy={out}
                    onClick={() => props.onRemove(id)}
                  >
                    {out ? "Removing…" : "Remove key"}
                  </button>
                ) : null}
                <button
                  className="run"
                  type="button"
                  disabled={missing}
                  onClick={() => props.onSave(id)}
                >
                  Save {name} key
                </button>
              </div>
              {cardNote(id, out ? "Removing…" : "")}
            </div>
          );
        })}
      </div>
    </div>
  );
}
