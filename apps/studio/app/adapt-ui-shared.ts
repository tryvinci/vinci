export type AdaptPresetRow = {
  id: string;
  label: string;
  platform?: string;
  partner?: string;
  spec_kind?: string;
  source?: "generic" | "partner" | "custom" | string;
  width: number;
  height: number;
  safe_area?: { top: number; bottom: number; left: number; right: number };
  safe_rect?: { left: number; right: number; top: number; bottom: number; content_width?: number; content_height?: number };
  human_review_advisories?: string[];
  export_validation?: {
    byte_cap?: { max_bytes: number; op: string } | null;
  };
};

export type AdaptTarget = { preset_id?: string; width?: number; height?: number };

export type AdaptCheck = {
  preset_id: string;
  asset_id: string;
  width: number;
  height: number;
  dimensions: { pass: boolean; actual_width?: number; actual_height?: number };
  byte_cap: { max_bytes: number; op: string; actual_bytes: number; pass: boolean } | null;
  safe_area: {
    applied: boolean;
    margins_px: { left: number; right: number; top: number; bottom: number } | null;
  };
};

export type BatchItemStatus = {
  index: number;
  asset_id?: string | null;
  status: "queued" | "running" | "done" | "failed" | string;
  error?: string | null;
  preset_ids: string[];
  output_asset_ids: string[];
  outputs: AdaptCheck[];
};

export type BatchStatus = { batch_id: string; items: BatchItemStatus[] };

export function presetLabel(preset: AdaptPresetRow | undefined, target: AdaptTarget, index: number): string {
  if (preset?.label) return preset.label;
  if (target.width && target.height) return `${target.width}×${target.height}`;
  return `Target ${index + 1}`;
}

export function engineLabel(layout: "fit_pad_crop" | "ai_extend", liveSpend: boolean): { text: string; real: boolean } {
  if (layout === "ai_extend") {
    return { text: liveSpend ? "AI extend" : "AI extend · off", real: liveSpend };
  }
  return { text: "ffmpeg · $0", real: true };
}

export function sourceOf(preset: AdaptPresetRow): "generic" | "partner" | "custom" {
  if (preset.source === "custom" || preset.source === "partner" || preset.source === "generic") {
    return preset.source;
  }
  if (preset.spec_kind === "client_partner") return "partner";
  if (preset.spec_kind === "custom") return "custom";
  return "generic";
}

export function byteCapLabel(preset: AdaptPresetRow): string | null {
  const cap = preset.export_validation?.byte_cap;
  if (!cap || !cap.max_bytes) return null;
  const kb = cap.max_bytes / 1024;
  const shown = Number.isInteger(kb) ? String(kb) : kb.toFixed(1);
  return `${cap.op === "lt" ? "<" : "≤"} ${shown} KB`;
}

export function groupPresets(rows: AdaptPresetRow[]): { partner: string; rows: AdaptPresetRow[] }[] {
  const order: string[] = [];
  const map = new Map<string, AdaptPresetRow[]>();
  for (const row of rows) {
    const key = row.partner || row.platform || "other";
    if (!map.has(key)) {
      map.set(key, []);
      order.push(key);
    }
    map.get(key)?.push(row);
  }
  return order.map((partner) => ({ partner, rows: map.get(partner) || [] }));
}

export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const kb = n / 1024;
  if (kb < 10) return `${kb.toFixed(1)} KB`;
  return `${Math.round(kb)} KB`;
}
