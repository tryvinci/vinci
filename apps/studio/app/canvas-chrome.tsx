"use client";

import { useEffect, useState } from "react";
import {
  EDGE_STYLES,
  NODE_H,
  NODE_W,
  RUN_SCOPES,
  type EdgeStyle,
  type RunScope,
  type Viewport,
} from "../lib/canvas-graph";
import {
  MINIMAP_H,
  MINIMAP_W,
  minimapPoint,
  minimapWorld,
  receiptAssets,
  receiptCosts,
  receiptNodes,
  receiptTotal,
  type BoardPage,
  type RunReceipt,
} from "../lib/canvas-board";

type Epoch = { epoch: number };

function useClosed(epoch: number) {
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [epoch]);
  return [open, setOpen] as const;
}

function Icon({ d }: { d: string }) {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d={d} stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

const PATH = {
  add: "M8 3v10M3 8h10",
  select: "M4 2.5 L4 12.5 L7 9.5 L10.5 13.5 L12 12.5 L8.5 8.5 L12.5 8 Z",
  pan: "M6 8 V4.5 M6 6.5 L3.5 8.5 M6 6.5 L8.5 8.5 M8 8.5 V5 M10 9 V6 M8 11.5 h2.5 a2 2 0 0 0 2-2 V8",
  note: "M4 3 h8 v7 l-3 3 H4 Z M9 13 v-3 h3",
  comment: "M3 4 h10 v6 H7 L4 13 V10 H3 Z",
  undo: "M6 4 H3 v3 M3.5 7 A5 5 0 1 0 5 4.2",
  redo: "M10 4 h3 v3 M12.5 7 A5 5 0 1 1 11 4.2",
  history: "M8 4 v4 l2.5 1.5 M8 13 a5 5 0 1 0-4-2",
  duplicate: "M6 5 h6 v7 H6 Z M4 8 V3 h7",
  instance: "M5 6 h6 v6 H5 Z M8 3 v3 M5 4 h6",
  trash: "M4 5 h8 M6 5 V4 h4 v1 M6 7 v4 M10 7 v4 M5 5 l.5 8 h5 L11 5",
  more: "M4 8 h.01 M8 8 h.01 M12 8 h.01",
  edge: "M3 11 C6 11 6 5 13 5",
};

/**
 * Left-edge Magnific tools. Round glass buttons, not a top row.
 * N add, V select, H pan, note, C comment, undo, redo, history.
 */
export function EdgeTools({
  tool,
  canUndo,
  canRedo,
  historyOpen,
  onAdd,
  onSelect,
  onPan,
  onNote,
  onComment,
  onUndo,
  onRedo,
  onHistory,
  addTitle,
  selectTitle,
  panTitle,
  commentTitle,
  undoTitle,
  redoTitle,
}: {
  tool: "select" | "pan" | "note" | "comment";
  canUndo: boolean;
  canRedo: boolean;
  historyOpen: boolean;
  onAdd: () => void;
  onSelect: () => void;
  onPan: () => void;
  onNote: () => void;
  onComment: () => void;
  onUndo: () => void;
  onRedo: () => void;
  onHistory: () => void;
  addTitle: string;
  selectTitle: string;
  panTitle: string;
  commentTitle: string;
  undoTitle: string;
  redoTitle: string;
}) {
  const btn = (
    id: string,
    label: string,
    icon: string,
    onClick: () => void,
    opts?: { pressed?: boolean; disabled?: boolean; title?: string },
  ) => (
    <button
      type="button"
      className={"icon-round" + (opts?.pressed ? " on" : "")}
      data-testid={id}
      aria-label={label}
      title={opts?.title || label}
      aria-pressed={opts?.pressed || undefined}
      disabled={opts?.disabled}
      onClick={onClick}
    >
      <Icon d={icon} />
    </button>
  );
  return (
    <div className="float-glass edge-tools" role="toolbar" aria-label="Canvas tools" data-testid="edge-tools" onPointerDown={(ev) => ev.stopPropagation()}>
      {btn("canvas-tool-add", "Add node", PATH.add, onAdd, { title: addTitle })}
      {btn("canvas-tool-select", "Select", PATH.select, onSelect, { pressed: tool === "select", title: selectTitle })}
      {btn("canvas-tool-pan", "Pan", PATH.pan, onPan, { pressed: tool === "pan", title: panTitle })}
      {btn("canvas-tool-note", "Note", PATH.note, onNote, { pressed: tool === "note" })}
      {btn("canvas-tool-comment", "Comment", PATH.comment, onComment, { pressed: tool === "comment", title: commentTitle })}
      {btn("canvas-tool-undo", "Undo", PATH.undo, onUndo, { disabled: !canUndo, title: undoTitle })}
      {btn("canvas-tool-redo", "Redo", PATH.redo, onRedo, { disabled: !canRedo, title: redoTitle })}
      {btn("canvas-tool-history", "History", PATH.history, onHistory, { pressed: historyOpen })}
    </div>
  );
}

type ScopeRow = { id: RunScope; label: string; cost: string };

/**
 * Floating bar on the selection. The run control shows the scope's cost before the name.
 * Scope, edge style, and More are button menus, not native selects.
 */
export function SelectionBar({
  epoch,
  x,
  y,
  below,
  scope,
  scopes,
  cost,
  edgeStyle,
  runDisabled,
  runTitle,
  showRun,
  canDuplicate,
  canInstance,
  canDelete,
  canGroup,
  canUngroup,
  onRun,
  onScope,
  onEdgeStyle,
  onDuplicate,
  onInstance,
  onDelete,
  onGroup,
  onUngroup,
}: Epoch & {
  x: number;
  y: number;
  below: boolean;
  scope: RunScope;
  scopes: ScopeRow[];
  cost: string;
  edgeStyle: EdgeStyle | null;
  runDisabled: boolean;
  runTitle: string;
  showRun: boolean;
  canDuplicate: boolean;
  canInstance: boolean;
  canDelete: boolean;
  canGroup: boolean;
  canUngroup: boolean;
  onRun: () => void;
  onScope: (scope: RunScope) => void;
  onEdgeStyle: (style: EdgeStyle) => void;
  onDuplicate: () => void;
  onInstance: () => void;
  onDelete: () => void;
  onGroup: () => void;
  onUngroup: () => void;
}) {
  const [scopeOpen, setScopeOpen] = useClosed(epoch);
  const [edgeOpen, setEdgeOpen] = useClosed(epoch);
  const [moreOpen, setMoreOpen] = useClosed(epoch);
  const label = RUN_SCOPES.find((row) => row.id === scope)?.label || "Up to here";
  return (
    <div
      className="float-glass selection-bar"
      role="toolbar"
      aria-label="Selection"
      data-testid="selection-bar"
      style={{ left: x, top: y, transform: below ? "translate(-50%, 8px)" : "translate(-50%, calc(-100% - 8px))" }}
      onPointerDown={(ev) => ev.stopPropagation()}
    >
      {showRun ? (
        <div className="sel-run">
          <button type="button" className="sel-go" data-testid="selection-run" disabled={runDisabled} title={runTitle} onClick={onRun}>
            <span data-testid="selection-cost">{cost || "$0"}</span>
            <span data-testid="selection-scope">{label}</span>
          </button>
          <button
            type="button"
            className={"icon-round" + (scopeOpen ? " on" : "")}
            data-testid="selection-scope-menu"
            aria-label="Run scope"
            aria-expanded={scopeOpen}
            onClick={() => setScopeOpen((open) => !open)}
          >
            ▾
          </button>
          {scopeOpen ? (
            <div className="float-menu" role="menu" data-testid="scope-menu">
              {scopes.map((row) => (
                <button
                  key={row.id}
                  type="button"
                  role="menuitem"
                  data-scope={row.id}
                  className={row.id === scope ? "on" : ""}
                  onClick={() => {
                    onScope(row.id);
                    setScopeOpen(false);
                  }}
                >
                  <span>{row.cost || "$0"}</span>
                  <span>{row.label}</span>
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
      <div className="float-pop">
        <button
          type="button"
          className={"icon-round" + (edgeOpen ? " on" : "")}
          data-testid="selection-edge"
          aria-label="Edge style"
          aria-expanded={edgeOpen}
          title="Edge style"
          onClick={() => setEdgeOpen((open) => !open)}
        >
          <Icon d={PATH.edge} />
        </button>
        {edgeOpen ? (
          <div className="float-menu" role="menu" data-testid="edge-menu">
            {EDGE_STYLES.map((row) => (
              <button
                key={row.id}
                type="button"
                role="menuitem"
                data-edge-style={row.id}
                className={edgeStyle === row.id ? "on" : ""}
                onClick={() => {
                  onEdgeStyle(row.id);
                  setEdgeOpen(false);
                }}
              >
                {row.label}
              </button>
            ))}
          </div>
        ) : null}
      </div>
      <button type="button" className="icon-round" data-testid="selection-duplicate" aria-label="Duplicate" disabled={!canDuplicate} onClick={onDuplicate}>
        <Icon d={PATH.duplicate} />
      </button>
      <button type="button" className="icon-round" data-testid="selection-instance" aria-label="Instance" disabled={!canInstance} onClick={onInstance}>
        <Icon d={PATH.instance} />
      </button>
      <button type="button" className="icon-round" data-testid="selection-delete" aria-label="Delete" disabled={!canDelete} onClick={onDelete}>
        <Icon d={PATH.trash} />
      </button>
      <div className="float-pop">
        <button
          type="button"
          className={"icon-round" + (moreOpen ? " on" : "")}
          data-testid="selection-more"
          aria-label="More"
          aria-expanded={moreOpen}
          onClick={() => setMoreOpen((open) => !open)}
        >
          <Icon d={PATH.more} />
        </button>
        {moreOpen ? (
          <div className="float-menu" role="menu" data-testid="selection-more-menu">
            <button type="button" role="menuitem" disabled={!canGroup} onClick={() => { onGroup(); setMoreOpen(false); }}>
              Group
            </button>
            <button type="button" role="menuitem" disabled={!canUngroup} onClick={() => { onUngroup(); setMoreOpen(false); }}>
              Ungroup
            </button>
          </div>
        ) : null}
      </div>
    </div>
  );
}

/** Bottom-left page switcher. Names are buttons; double-click renames. Add and remove are round. */
export function PageBar({
  pages,
  active,
  onOpen,
  onAdd,
  onRemove,
  onRename,
}: {
  pages: BoardPage[];
  active: string;
  onOpen: (id: string) => void;
  onAdd: () => void;
  onRemove: (id: string) => void;
  onRename: (id: string, name: string) => void;
}) {
  const [renaming, setRenaming] = useState<string | null>(null);
  return (
    <div className="float-glass page-bar" data-testid="canvas-pages" role="tablist" aria-label="Pages" onPointerDown={(ev) => ev.stopPropagation()}>
      {pages.map((page) =>
        renaming === page.id ? (
          <input
            key={page.id}
            autoFocus
            aria-label="Page name"
            defaultValue={page.name}
            onKeyDown={(ev) => {
              if (ev.key === "Enter") ev.currentTarget.blur();
              if (ev.key === "Escape") {
                ev.currentTarget.dataset.cancel = "1";
                ev.currentTarget.blur();
              }
            }}
            onBlur={(ev) => {
              if (ev.currentTarget.dataset.cancel !== "1") onRename(page.id, ev.currentTarget.value);
              setRenaming(null);
            }}
          />
        ) : (
          <button
            key={page.id}
            type="button"
            role="tab"
            data-testid="page-tab"
            data-page={page.id}
            aria-selected={page.id === active}
            className={page.id === active ? "on" : ""}
            onClick={() => onOpen(page.id)}
            onDoubleClick={() => setRenaming(page.id)}
          >
            {page.name}
          </button>
        ),
      )}
      <button type="button" className="icon-round" data-testid="page-add" aria-label="Add page" onClick={onAdd}>
        <Icon d={PATH.add} />
      </button>
      {pages.length > 1 ? (
        <button type="button" className="icon-round" data-testid="page-remove" aria-label="Remove page" onClick={() => onRemove(active)}>
          ×
        </button>
      ) : null}
    </div>
  );
}

/** Bottom-right minimap and zoom menu. Fit, fit selection, and 100% use the canvas shortcuts. */
export function MinimapZoom({
  epoch,
  nodes,
  view,
  boardW,
  boardH,
  onPan,
  onZoomIn,
  onZoomOut,
  onFit,
  onFitSelection,
  onReset,
}: Epoch & {
  nodes: readonly { id: string; x?: number; y?: number }[];
  view: Viewport;
  boardW: number;
  boardH: number;
  onPan: (mx: number, my: number) => void;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onFit: () => void;
  onFitSelection: () => void;
  onReset: () => void;
}) {
  const [open, setOpen] = useClosed(epoch);
  const world = minimapWorld(nodes, view, Math.max(boardW, 1), Math.max(boardH, 1));
  const viewOrigin = minimapPoint(world, MINIMAP_W, MINIMAP_H, -view.x / view.zoom, -view.y / view.zoom);
  const viewSize = minimapPoint(world, MINIMAP_W, MINIMAP_H, -view.x / view.zoom + boardW / view.zoom, -view.y / view.zoom + boardH / view.zoom);
  return (
    <div className="minimap-dock" onPointerDown={(ev) => ev.stopPropagation()}>
      <div className="float-pop zoom-pop">
        <button
          type="button"
          className="zoom-pct"
          data-testid="canvas-zoom"
          aria-label="Zoom menu"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          {Math.round(view.zoom * 100)}%
        </button>
        {open ? (
          <div className="float-menu" role="menu" data-testid="zoom-menu">
            <button type="button" role="menuitem" onClick={() => { onZoomIn(); setOpen(false); }}>Zoom in</button>
            <button type="button" role="menuitem" onClick={() => { onZoomOut(); setOpen(false); }}>Zoom out</button>
            <button type="button" role="menuitem" onClick={() => { onFit(); setOpen(false); }}>
              <span>Fit</span><kbd>D</kbd>
            </button>
            <button type="button" role="menuitem" onClick={() => { onFitSelection(); setOpen(false); }}>
              <span>Fit selection</span><kbd>F</kbd>
            </button>
            <button type="button" role="menuitem" onClick={() => { onReset(); setOpen(false); }}>
              <span>100%</span><kbd>⌘0</kbd>
            </button>
          </div>
        ) : null}
      </div>
      <svg
        className="float-glass minimap"
        data-testid="canvas-minimap"
        width={MINIMAP_W}
        height={MINIMAP_H}
        viewBox={`0 0 ${MINIMAP_W} ${MINIMAP_H}`}
        role="img"
        aria-label="Minimap"
        onPointerDown={(ev) => {
          const rect = ev.currentTarget.getBoundingClientRect();
          onPan(ev.clientX - rect.left, ev.clientY - rect.top);
        }}
      >
        {nodes.map((node) => {
          const at = minimapPoint(world, MINIMAP_W, MINIMAP_H, node.x || 0, node.y || 0);
          const far = minimapPoint(world, MINIMAP_W, MINIMAP_H, (node.x || 0) + NODE_W, (node.y || 0) + NODE_H);
          return <rect key={node.id} x={at.x} y={at.y} width={Math.max(2, far.x - at.x)} height={Math.max(2, far.y - at.y)} />;
        })}
        <rect className="minimap-view" x={viewOrigin.x} y={viewOrigin.y} width={Math.max(4, viewSize.x - viewOrigin.x)} height={Math.max(4, viewSize.y - viewOrigin.y)} />
      </svg>
    </div>
  );
}

/** Receipt history. Tabs are Cost, Assets, and Nodes. Dollars come from run receipts. */
export function HistoryPanel({
  open,
  runs,
  money,
  onClose,
}: {
  open: boolean;
  runs: readonly RunReceipt[];
  money: (n: number) => string;
  onClose: () => void;
}) {
  const [tab, setTab] = useState<"cost" | "assets" | "nodes">("cost");
  if (!open) return null;
  const costs = receiptCosts(runs);
  const assets = receiptAssets(runs);
  const nodes = receiptNodes(runs);
  return (
    <aside className="float-glass history-panel" data-testid="canvas-history" aria-label="History" onPointerDown={(ev) => ev.stopPropagation()}>
      <header>
        <strong>History</strong>
        <button type="button" className="icon-round" aria-label="Close history" onClick={onClose}>
          ×
        </button>
      </header>
      <div className="history-tabs" role="tablist">
        {(["cost", "assets", "nodes"] as const).map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            data-testid={"history-tab-" + id}
            aria-selected={tab === id}
            className={tab === id ? "on" : ""}
            onClick={() => setTab(id)}
          >
            {id === "cost" ? "Cost" : id === "assets" ? "Assets" : "Nodes"}
          </button>
        ))}
      </div>
      {tab === "cost" ? (
        <div data-testid="history-cost">
          <p className="history-total">{money(receiptTotal(runs))}</p>
          {costs.length === 0 ? <p className="muted">No receipts yet.</p> : null}
          {costs.map((row) => (
            <div key={row.id} className="history-row">
              <span>{money(row.dollars)}</span>
              <span className="muted">{row.state || row.id}</span>
            </div>
          ))}
        </div>
      ) : null}
      {tab === "assets" ? (
        <div data-testid="history-assets">
          {assets.length === 0 ? <p className="muted">No assets yet.</p> : null}
          {assets.map((row) => (
            <div key={row.runId + row.assetId} className="history-row">
              <span>{row.assetId}</span>
            </div>
          ))}
        </div>
      ) : null}
      {tab === "nodes" ? (
        <div data-testid="history-nodes">
          {nodes.length === 0 ? <p className="muted">No nodes yet.</p> : null}
          {nodes.map((row) => (
            <div key={row.runId + row.nodeId} className="history-row">
              <span>{row.nodeId}</span>
              <span className="muted">{row.assetId || "no output"}</span>
            </div>
          ))}
        </div>
      ) : null}
    </aside>
  );
}
