from __future__ import annotations

from abc import ABC, abstractmethod

from vinci_protocol.enums import Capability
from vinci_protocol.models import (
    Estimate,
    JobRequest,
    JobStatus,
    ModelSpec,
    ProviderJobRef,
    ProviderManifest,
    VinciError,
)


class Provider(ABC):
    """Plugin contract. Implementations must pass the conformance suite."""

    manifest: ProviderManifest

    @abstractmethod
    def catalog(self) -> list[ModelSpec]:
        raise NotImplementedError

    @abstractmethod
    def capabilities(self) -> set[Capability]:
        raise NotImplementedError

    @abstractmethod
    def estimate(self, req: JobRequest) -> Estimate:
        raise NotImplementedError

    @abstractmethod
    def submit(self, req: JobRequest) -> ProviderJobRef:
        raise NotImplementedError

    @abstractmethod
    def status(self, ref: ProviderJobRef) -> JobStatus:
        raise NotImplementedError

    @abstractmethod
    def cancel(self, ref: ProviderJobRef) -> None:
        raise NotImplementedError

    @abstractmethod
    def normalize_error(self, exc: BaseException) -> VinciError:
        raise NotImplementedError
