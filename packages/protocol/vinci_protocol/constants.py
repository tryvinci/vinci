PROTOCOL_VERSION = "0.1.0"

JOB_STATES = (
    "created",
    "awaiting_approval",
    "queued",
    "running",
    "completed",
    "failed",
    "cancelled",
)

ERROR_CODES = (
    "auth",
    "quota",
    "rate_limit",
    "invalid_input",
    "content_policy",
    "provider_down",
    "timeout",
    "cancelled",
    "unknown",
)

CAPABILITIES = (
    "t2i",
    "i2i",
    "t2v",
    "i2v",
    "lipsync",
    "tts",
    "sts",
    "voice_clone",
    "upscale",
    "transcribe",
    "reframe",
    "caption",
    "edit_multi",
)

ASSET_KINDS = ("image", "video", "audio", "text", "timeline")
ASSET_SOURCES = ("generated", "uploaded", "derived")
MODEL_STATUSES = ("active", "deprecated", "sunset")
NODE_TYPES = ("generate", "transform", "media", "indexquery", "gate")
PREFERENCES = ("cheapest", "fastest", "quality")
