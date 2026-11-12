"use client";

/**
 * Connect on a host such as Vinci Platform: the user's own API keys for the providers the host
 * takes (`doctor.host.keys`). A run on one of these keys costs no host credits, because the
 * provider bills the user's account. The host stores the key encrypted and shows only its last
 * 4 characters (hosted own keys, COREPRODUC-613).
 */

type KeyRow = {
  configured?: boolean;
  available?: boolean;
  display_name?: string;
  key_hint?: string;
};

const NAMES: Record<string, string> = {
  wavespeed: "Wavespeed",
  magnific: "Magnific",
  higgsfield: "Higgsfield",
};
const NOTES: Record<string, string> = {
  wavespeed: "The Studio's models run on your key and show its dollar price.",
  magnific: "Adds the Magnific image and video models.",
  higgsfield:
    "Adds the Higgsfield image and video models. Higgsfield needs the key and the secret.",
};
// Providers whose sign-in has a second secret (the daemon's extra_secret).
const EXTRA: Record<string, string> = { higgsfield: "API secret" };

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
  log: string;
}) {
  const { draft, setDraft } = props;
  return (
    <div className="keys connect host-keys" data-testid="host-keys">
      <p className="eyebrow">{props.hostName}</p>
      <h2>Your API keys</h2>
      <p className="muted lede">
        Run models on your own provider account. Runs on your key cost no
        credits: the provider bills you. The key is stored encrypted, and this
        page shows only its last 4 characters.
      </p>
      <div className="host-key-list">
        {props.keys.map((id) => {
          const row = props.providers[id];
          const name = row?.display_name || NAMES[id] || id;
          const ready = Boolean(row?.configured);
          const missing =
            !(draft[`key-${id}`] || "").trim() ||
            (EXTRA[id] ? !(draft[`extra-${id}`] || "").trim() : false);
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
              {EXTRA[id] ? (
                <>
                  <label htmlFor={`extra-${id}`}>{EXTRA[id]}</label>
                  <input
                    id={`extra-${id}`}
                    type="password"
                    autoComplete="new-password"
                    value={draft[`extra-${id}`] || ""}
                    onChange={(ev) =>
                      setDraft((d) => ({
                        ...d,
                        [`extra-${id}`]: ev.target.value,
                      }))
                    }
                    placeholder={`${name} ${EXTRA[id]}`}
                  />
                </>
              ) : null}
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
        <p className="log" role="status">
          {props.log}
        </p>
      ) : null}
    </div>
  );
}
