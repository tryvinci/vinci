"use client";

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
  log: string;
  /** The log is an error (the last save failed). */
  error?: boolean;
}) {
  const { draft, setDraft } = props;
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
          if (id.startsWith("mcp_")) {
            const signedIn = row?.auth_state === "connected";
            return (
              <div className="connect-sheet" key={id} data-host-key={id}>
                <span className="kind">Sign-in</span>
                <strong>{name}</strong>
                <div className="muted">{signInState(row)}</div>
                <p className="muted">{NOTES[id] || ""}</p>
                <ProviderLink id={id} />
                <div className="file-row">
                  {row?.configured ? (
                    <button
                      className="ghost"
                      type="button"
                      onClick={() => props.onRemove(id)}
                    >
                      Sign out
                    </button>
                  ) : null}
                  {signedIn ? null : (
                    <button
                      className="run"
                      type="button"
                      onClick={() => props.onSignIn(id)}
                    >
                      Sign in to {name}
                    </button>
                  )}
                </div>
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
                    onClick={() => props.onRemove(id)}
                  >
                    Remove key
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
            </div>
          );
        })}
      </div>
      {props.log ? (
        <p className={props.error ? "log error" : "log"} role={props.error ? "alert" : "status"} data-testid="host-keys-log">
          {props.log}
        </p>
      ) : null}
    </div>
  );
}
