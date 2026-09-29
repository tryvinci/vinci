export const PROTOCOL_VERSION = "0.1.0";

export type JobState =
  | "created"
  | "awaiting_approval"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type ErrorCode =
  | "auth"
  | "quota"
  | "rate_limit"
  | "invalid_input"
  | "content_policy"
  | "provider_down"
  | "timeout"
  | "cancelled"
  | "unknown";

export type Capability =
  | "t2i"
  | "i2i"
  | "t2v"
  | "i2v"
  | "lipsync"
  | "tts"
  | "sts"
  | "voice_clone"
  | "upscale"
  | "transcribe"
  | "reframe"
  | "caption"
  | "edit_multi";

export type AssetKind = "image" | "video" | "audio" | "text" | "timeline";
export type AssetSource = "generated" | "uploaded" | "derived";
export type ModelStatus = "active" | "deprecated" | "sunset";
export type NodeType = "generate" | "transform" | "media" | "indexquery" | "gate";
export type RoutePreference = "cheapest" | "fastest" | "quality";

export interface Provenance {
  skill?: string | null;
  model_id?: string | null;
}

export interface Asset {
  id: string;
  kind: AssetKind;
  mime: string;
  bytes: number;
  width?: number | null;
  height?: number | null;
  duration?: number | null;
  source: AssetSource;
  parent_ids: string[];
  created_by?: Provenance | null;
  metadata?: Record<string, unknown>;
  created_at: string;
  uri?: string | null;
}

export interface Pricing {
  unit: string;
  amount: number;
  currency: string;
  snapshot_at: string;
}

export interface ModelSpec {
  id: string;
  display_name: string;
  provider: string;
  capabilities: Capability[];
  constraints?: {
    aspect_ratios?: string[];
    max_duration?: number | null;
    resolutions?: string[];
    max_input_images?: number | null;
  };
  pricing: Pricing;
  quality_tier?: string;
  status?: ModelStatus;
  secret_names?: string[];
}

export interface VinciError {
  code: ErrorCode;
  message: string;
  provider?: string | null;
  retryable?: boolean;
  details?: Record<string, unknown>;
}

export interface Estimate {
  model_id: string;
  provider: string;
  amount: number;
  currency: string;
  unit: string;
  unit_count: number;
  pricing_snapshot_at: string;
  alternative?: Record<string, unknown> | null;
  cached?: boolean;
}

export interface Receipt {
  job_id: string;
  model_id: string;
  provider: string;
  list_price: number;
  unit_count: number;
  computed_cost: number;
  currency: string;
  pricing_snapshot_at: string;
  retries_cost?: number;
  wall_time?: number;
  cached?: boolean;
}

export interface Job {
  id: string;
  workflow_run_id?: string | null;
  node_id?: string | null;
  model_id: string;
  provider_job_ref?: string | null;
  state: JobState;
  inputs?: Record<string, unknown>;
  outputs?: string[];
  estimate?: Estimate | null;
  receipt?: Receipt | null;
  error?: VinciError | null;
  retries?: number;
  idempotency_key?: string | null;
  protocol_version?: string;
}

export interface WorkflowNode {
  id: string;
  type: NodeType;
  capability?: Capability | null;
  model_id?: string | null;
  params?: Record<string, unknown>;
  budget_hint?: number | null;
}

export interface WorkflowSpec {
  id: string;
  version: string;
  nodes: WorkflowNode[];
  edges?: { src: string; dst: string; input_key?: string | null }[];
  preference?: RoutePreference;
  max_cost?: number | null;
}

export interface VinciEvent {
  type: string;
  job_id?: string | null;
  run_id?: string | null;
  created_at: string;
  payload?: Record<string, unknown>;
}

export interface Handshake {
  protocol_version: string;
  daemon_version?: string | null;
}

export interface TimelineClip {
  asset_id: string;
  start?: number;
  end?: number | null;
  track?: string;
}

export interface Timeline {
  id: string;
  clips: TimelineClip[];
  fps?: number | null;
  width?: number | null;
  height?: number | null;
}

export const assetUri = (id: string): string => `vinci://assets/${id}`;
export const jobUri = (id: string): string => `vinci://jobs/${id}`;
export const receiptUri = (id: string): string => `vinci://receipts/${id}`;
