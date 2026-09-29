"""Example: mock t2i through the provider SDK (no network, $0)."""

from pathlib import Path

from vinci_protocol.enums import Capability
from vinci_protocol.models import JobRequest
from vinci_provider_sdk.mock import MockProvider
from vinci_storage.cas import ContentAddressedStore


def main() -> None:
    cas = ContentAddressedStore(Path(".vinci-home") / "cas")
    provider = MockProvider(cas)
    req = JobRequest(capability=Capability.T2I, inputs={"prompt": "a red cube"})
    estimate = provider.estimate(req)
    ref = provider.submit(req)
    status = provider.status(ref)
    print({"estimate": estimate.amount, "outputs": status.outputs, "ref": ref.ref})


if __name__ == "__main__":
    main()
