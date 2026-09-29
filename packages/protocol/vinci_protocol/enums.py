from enum import StrEnum

from vinci_protocol.constants import (
    ASSET_KINDS,
    ASSET_SOURCES,
    CAPABILITIES,
    ERROR_CODES,
    JOB_STATES,
    MODEL_STATUSES,
    NODE_TYPES,
    PREFERENCES,
)


class JobState(StrEnum):
    CREATED = "created"
    AWAITING_APPROVAL = "awaiting_approval"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ErrorCode(StrEnum):
    AUTH = "auth"
    QUOTA = "quota"
    RATE_LIMIT = "rate_limit"
    INVALID_INPUT = "invalid_input"
    CONTENT_POLICY = "content_policy"
    PROVIDER_DOWN = "provider_down"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"


class Capability(StrEnum):
    T2I = "t2i"
    I2I = "i2i"
    T2V = "t2v"
    I2V = "i2v"
    LIPSYNC = "lipsync"
    TTS = "tts"
    STS = "sts"
    VOICE_CLONE = "voice_clone"
    UPSCALE = "upscale"
    TRANSCRIBE = "transcribe"
    REFRAME = "reframe"
    CAPTION = "caption"
    EDIT_MULTI = "edit_multi"


class AssetKind(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    AUDIO = "audio"
    TEXT = "text"
    TIMELINE = "timeline"


class AssetSource(StrEnum):
    GENERATED = "generated"
    UPLOADED = "uploaded"
    DERIVED = "derived"


class ModelStatus(StrEnum):
    ACTIVE = "active"
    DEPRECATED = "deprecated"
    SUNSET = "sunset"


class NodeType(StrEnum):
    GENERATE = "generate"
    TRANSFORM = "transform"
    MEDIA = "media"
    INDEXQUERY = "indexquery"
    GATE = "gate"


class RoutePreference(StrEnum):
    CHEAPEST = "cheapest"
    FASTEST = "fastest"
    QUALITY = "quality"


def _assert_enum_covers(enum_cls: type[StrEnum], values: tuple[str, ...]) -> None:
    members = {m.value for m in enum_cls}
    expected = set(values)
    if members != expected:
        raise RuntimeError(f"{enum_cls.__name__} drift: {members ^ expected}")


_assert_enum_covers(JobState, JOB_STATES)
_assert_enum_covers(ErrorCode, ERROR_CODES)
_assert_enum_covers(Capability, CAPABILITIES)
_assert_enum_covers(AssetKind, ASSET_KINDS)
_assert_enum_covers(AssetSource, ASSET_SOURCES)
_assert_enum_covers(ModelStatus, MODEL_STATUSES)
_assert_enum_covers(NodeType, NODE_TYPES)
_assert_enum_covers(RoutePreference, PREFERENCES)
