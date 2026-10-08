/** Pending submit_intent → committed provider_job_ref upgrade guards (parity with journal_payload.py). */

const PROVIDER_INFLIGHT_INTENT_KEYS = [
  "run_id",
  "node_id",
  "job_id",
  "model_id",
  "provider",
  "idempotency_key",
] as const;

export function providerSubmitIntentFieldsMatch(
  existingPayload: Record<string, unknown>,
  commitPayload: Record<string, unknown>,
  existingKind: string,
  existingPath: string,
  commitKind: string,
  commitPath: string,
): boolean {
  if (existingKind !== commitKind || existingPath !== commitPath) {
    return false;
  }
  for (const key of PROVIDER_INFLIGHT_INTENT_KEYS) {
    if (String(existingPayload[key] ?? "") !== String(commitPayload[key] ?? "")) {
      return false;
    }
  }
  return true;
}

export function allowProviderSubmitRefUpgrade(
  existingStatus: string,
  existingPayload: Record<string, unknown>,
  commitPayload: Record<string, unknown>,
  existingKind: string,
  existingPath: string,
  commitKind: string,
  commitPath: string,
): boolean {
  if (existingStatus !== "pending") {
    return false;
  }
  if (!existingPayload.submit_intent) {
    return false;
  }
  if (String(existingPayload.provider_job_ref ?? "")) {
    return false;
  }
  if (!String(commitPayload.provider_job_ref ?? "")) {
    return false;
  }
  return providerSubmitIntentFieldsMatch(
    existingPayload,
    commitPayload,
    existingKind,
    existingPath,
    commitKind,
    commitPath,
  );
}
