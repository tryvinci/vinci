"use client";

import { useEffect, useState } from "react";

/** The local daemon, as `vinci mcp print-config` prints it (apps/cli/src/index.ts). */
const LOCAL_MCP = "http://127.0.0.1:4310/mcp";
const DOCS = "https://docs.tryvinci.com/agents";

/**
 * "Connect an agent" on Connect (COREPRODUC-777): the copy-paste setup of Claude Code, claude.ai and
 * Cursor for the Vinci MCP server. A host serves it at `<origin>/mcp` and signs the agent in with
 * the user's Vinci account (OAuth, no key); the local Studio points at the daemon's `/mcp`.
 *
 * Args (props):
 *   hosted: True inside a host (`doctor.host`): the page origin's `/mcp`, else the local daemon.
 */
export function AgentConnect({ hosted }: { hosted: boolean }) {
  // The origin is read after mount: the static export renders this page with no window.
  const [url, setUrl] = useState(hosted ? "" : LOCAL_MCP);
  const [copied, setCopied] = useState("");
  useEffect(() => {
    if (hosted) setUrl(`${window.location.origin}/mcp`);
  }, [hosted]);
  const config = JSON.stringify({ mcpServers: { vinci: { url } } }, null, 2);
  const rows = [
    ["Claude Code", `claude mcp add --transport http vinci ${url}`, hosted ? "Then run /mcp → vinci → Authenticate." : ""],
    hosted ? ["claude.ai", url, "Settings → Connectors → Add custom connector, then paste this address."] : null,
    [hosted ? "Cursor" : "Cursor and other clients", config, `Put it in ~/.cursor/mcp.json.${hosted ? "" : " vinci mcp print-config prints it."}`],
  ].filter(Boolean) as [string, string, string][];
  const copy = (name: string, text: string) =>
    navigator.clipboard.writeText(text).then(
      () => {
        console.info("[connect] agent setup copied", { name, url });
        setCopied(`Copied the ${name} setup.`);
      },
      (err) => setCopied(`Could not copy: ${err instanceof Error ? err.message : String(err)}`),
    );
  return (
    <div className="connect-sheet agent-connect" data-testid="agent-connect">
      <span className="kind">Agent</span>
      <strong>Connect an agent</strong>
      <p className="muted">
        {hosted
          ? "Your agent uses this Studio. It signs in with your Vinci account: no key."
          : "Your agent uses this Studio on this computer."}{" "}
        {hosted ? "Runs use your credits, or your own account." : "Runs use your provider keys."} The agent gets the price before it runs.
      </p>
      {rows.map(([name, text, note]) => (
        <div className="agent-row" key={name} data-agent={name}>
          <label>{name}</label>
          <pre className="agent-snippet">{text}</pre>
          <div className="file-row">
            <button className="ghost" type="button" disabled={!url} onClick={() => void copy(name, text)}>
              Copy
            </button>
            {note ? <small className="muted">{note}</small> : null}
          </div>
        </div>
      ))}
      <p className="muted">
        <a href={DOCS} target="_blank" rel="noreferrer">Agent setup docs</a>
      </p>
      <p className="log" role="status">{copied}</p>
    </div>
  );
}
