/**
 * What a catalog row takes besides the prompt (COREPRODUC-667): an end frame, open references.
 * No imports: the Video page rules and the model menu both use it.
 */

type InputsRow = {
  id: string;
  display_name: string;
  capabilities?: string[];
  constraints?: { end_frame?: boolean; max_references?: number; max_input_images?: number | null };
};

/** True for a video model. */
export function isVideoRow(model: InputsRow): boolean {
  return (model.capabilities || []).some((c) => c === "t2v" || c === "i2v");
}

/** True when the model takes open reference images (a video's References mode, an image edit). */
export function takesReferences(model: InputsRow): boolean {
  if (isVideoRow(model)) return Number(model.constraints?.max_references || 0) > 0;
  return (model.capabilities || []).includes("i2i") || Number(model.constraints?.max_input_images || 0) > 1;
}

/** True when a video model takes an end frame: the catalog flag, else a first-last id. */
export function takesEndFrame(model: InputsRow): boolean {
  if (model.constraints?.end_frame) return true;
  return /flf|first.?last/.test(`${model.id} ${model.display_name}`.toLowerCase());
}
