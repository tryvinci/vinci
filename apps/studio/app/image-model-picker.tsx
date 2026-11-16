"use client";

import { type ImageModel } from "../lib/image-page";
import { ModelMenu } from "./model-menu";

/**
 * Upward model picker of the Image prompt bar: the shared model menu (COREPRODUC-666).
 *
 * Args:
 *   models: Image catalog rows.
 *   value: Selected model id.
 *   query: Search text.
 *   onQuery / onPick: Picker events. Escape and outside clicks are the parent bar's (useMenuEscape).
 */
export function ImageModelPicker({
  models,
  value,
  query,
  onQuery,
  onPick,
}: {
  models: ImageModel[];
  value: string;
  query: string;
  onQuery: (q: string) => void;
  onPick: (id: string) => void;
}) {
  return (
    <div className="image-picker" data-testid="image-model-picker" role="listbox" aria-label="Image models">
      <ModelMenu models={models} value={value} query={query} onQuery={onQuery} onPick={onPick} />
    </div>
  );
}
