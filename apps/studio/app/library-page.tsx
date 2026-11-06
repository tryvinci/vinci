"use client";

import { useRef, useState } from "react";
import {
  CUSTOM_TABS,
  LIBRARY_REF_LIMIT,
  REF_TABS,
  createLibraryItem,
  itemsForTab,
  tabKind,
  type LibraryItem,
  type LibraryKind,
  type LibraryTab,
} from "../lib/library";

type Template = { id: string; title: string; blurb: string };

/**
 * Magnific Library: References + Custom tabs, create = name + 1-8 images.
 *
 * Templates are the existing first-party skill graphs. Flows stay empty until
 * Spaces can save a selection — this page does not invent a second catalog.
 */
export function LibraryPage({
  items,
  tab,
  onTab,
  templates,
  onCreate,
  onOpenTemplate,
  onIngest,
}: {
  items: readonly LibraryItem[];
  tab: LibraryTab;
  onTab: (tab: LibraryTab) => void;
  templates: readonly Template[];
  onCreate: (item: LibraryItem) => void;
  onOpenTemplate: (id: string) => void;
  onIngest: (file: File) => Promise<{ id: string }>;
}) {
  const kind = tabKind(tab);
  const rows = itemsForTab(items, tab);
  return (
    <div className="lib-page library-page" data-testid="library-page">
      <h2>Library</h2>
      <p className="muted">Characters, Elements, Styles, and Locations. Type @ in any prompt to insert one.</p>
      <div className="library-layout">
        <nav className="library-nav" aria-label="Library tabs">
          <p className="eyebrow">References</p>
          {REF_TABS.map((row) => (
            <button
              key={row.id}
              type="button"
              className={tab === row.id ? "on" : ""}
              data-testid={`library-tab-${row.id}`}
              onClick={() => onTab(row.id)}
            >
              {row.label}
            </button>
          ))}
          <p className="eyebrow">Custom</p>
          {CUSTOM_TABS.map((row) => (
            <button
              key={row.id}
              type="button"
              className={tab === row.id ? "on" : ""}
              data-testid={`library-tab-${row.id}`}
              onClick={() => onTab(row.id)}
            >
              {row.label}
            </button>
          ))}
        </nav>
        <div className="library-main">
          {kind ? (
            <CreateForm
              kind={kind}
              onCreate={onCreate}
              onIngest={onIngest}
            />
          ) : null}
          {tab === "templates" ? (
            templates.length === 0 ? (
              <p className="muted" data-testid="library-empty">No templates on this machine.</p>
            ) : (
              <div className="library-grid" data-testid="library-templates">
                {templates.map((row) => (
                  <button key={row.id} type="button" className="library-card" onClick={() => onOpenTemplate(row.id)}>
                    <strong>{row.title}</strong>
                    <span className="muted">{row.blurb}</span>
                  </button>
                ))}
              </div>
            )
          ) : null}
          {tab === "flows" ? (
            <p className="muted" data-testid="library-empty">
              No flows yet. Save a canvas selection later.
            </p>
          ) : null}
          {kind && rows.length === 0 ? (
            <p className="muted" data-testid="library-empty">
              No {REF_TABS.find((row) => row.id === tab)?.label.toLowerCase()} yet.
            </p>
          ) : null}
          {kind && rows.length ? (
            <div className="library-grid" data-testid="library-grid">
              {rows.map((row) => (
                <article key={row.id} className="library-card" data-library-item={row.id}>
                  {row.refs[0] ? (
                    <img src={`/vinci-api/assets/${encodeURIComponent(row.refs[0])}/file`} alt="" />
                  ) : null}
                  <strong>{row.name}</strong>
                  <span className="muted">
                    {row.kind}
                    {row.refs.length > 1 ? ` · ${row.refs.length} refs` : ""}
                  </span>
                </article>
              ))}
            </div>
          ) : null}
        </div>
      </div>
    </div>
  );
}

function CreateForm({
  kind,
  onCreate,
  onIngest,
}: {
  kind: LibraryKind;
  onCreate: (item: LibraryItem) => void;
  onIngest: (file: File) => Promise<{ id: string }>;
}) {
  const [name, setName] = useState("");
  const [refs, setRefs] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function addFiles(files: FileList | null) {
    if (!files?.length) return;
    setBusy(true);
    setError("");
    try {
      const next = [...refs];
      for (const file of Array.from(files)) {
        if (next.length >= LIBRARY_REF_LIMIT) break;
        const asset = await onIngest(file);
        if (asset.id && !next.includes(asset.id)) next.push(asset.id);
      }
      setRefs(next);
      console.info("[library] create refs", { kind, count: next.length });
    } catch (err) {
      setError(String(err instanceof Error ? err.message : err));
    } finally {
      setBusy(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  function submit() {
    const made = createLibraryItem({ name, kind, refs });
    if (!made.ok) {
      setError(made.error);
      return;
    }
    onCreate(made.item);
    setName("");
    setRefs([]);
    setError("");
    console.info("[library] created", { id: made.item.id, kind, refs: made.item.refs.length });
  }

  return (
    <form
      className="library-create"
      data-testid="library-create"
      onSubmit={(ev) => {
        ev.preventDefault();
        submit();
      }}
    >
      <label htmlFor="library-name">Name</label>
      <input
        id="library-name"
        data-testid="library-name"
        value={name}
        placeholder="Name"
        onChange={(ev) => setName(ev.target.value)}
      />
      <div className="library-create-refs">
        {refs.map((id) => (
          <button
            key={id}
            type="button"
            className="library-ref"
            title="Remove image"
            onClick={() => setRefs((rows) => rows.filter((row) => row !== id))}
          >
            <img src={`/vinci-api/assets/${encodeURIComponent(id)}/file`} alt="" />
          </button>
        ))}
        {refs.length < LIBRARY_REF_LIMIT ? (
          <button
            type="button"
            className="library-ref-add"
            data-testid="library-add-image"
            disabled={busy}
            onClick={() => fileRef.current?.click()}
          >
            +
          </button>
        ) : null}
      </div>
      <input
        ref={fileRef}
        className="hidden"
        type="file"
        accept="image/*"
        multiple
        aria-label="Add images"
        onChange={(ev) => void addFiles(ev.target.files)}
      />
      <p className="muted">{refs.length}/{LIBRARY_REF_LIMIT} images</p>
      {error ? <p className="danger" data-testid="library-create-error">{error}</p> : null}
      <button className="run" type="submit" data-testid="library-create-submit" disabled={busy}>
        Create
      </button>
    </form>
  );
}
