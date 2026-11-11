"""C2PA provenance in exported files (COREPRODUC-544; SPEC.md, Takes: engines SHOULD write it).

Each exported MP4 gets a signed C2PA manifest: a ``c2pa.created`` action for AI-generated media,
and an ``org.tryvinci.olf`` assertion with the show, the episode and each take it shows (ID,
model, provider, created, license). The signer is local: a CA and an ES256 signing certificate
made on first use in ``$VINCI_HOME/c2pa/``. A reader sees a valid signature from a certificate
that is not on the C2PA trust list. Needs ``c2pa-python`` (``pip install 'vinci-olf[c2pa]'``).
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import logging
import os
from pathlib import Path
from typing import Any

from vinci_olf.project import OlfError, Project

log = logging.getLogger(__name__)
GENERATED = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"


def available() -> bool:
    """True when ``c2pa-python`` is installed."""
    return importlib.util.find_spec("c2pa") is not None


def local_signer(folder: Path) -> tuple[bytes, bytes]:
    """The local certificate chain (signer, then CA) and the signer's key, as PEM.

    Made once in ``folder``; the key file is readable by its owner only.
    """
    chain_path, key_path = folder / "chain.pem", folder / "signer.key"
    if chain_path.is_file() and key_path.is_file():
        return chain_path.read_bytes(), key_path.read_bytes()
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

    now = dt.datetime.now(dt.UTC)

    def cert(subject: str, key: Any, issuer: Any, signer: Any, *, ca: bool, days: int) -> Any:
        usage = {k: False for k in ("content_commitment", "key_encipherment", "data_encipherment")}
        usage |= {"key_agreement": False, "encipher_only": False, "decipher_only": False}
        name = x509.Name(
            [
                x509.NameAttribute(NameOID.COMMON_NAME, subject),
                x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Vinci (local)"),
            ]
        )
        build = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(issuer or name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(days=1))
            .not_valid_after(now + dt.timedelta(days=days))
            .add_extension(
                x509.BasicConstraints(ca=ca, path_length=0 if ca else None), critical=True
            )
            .add_extension(
                x509.KeyUsage(digital_signature=True, key_cert_sign=ca, crl_sign=ca, **usage),
                critical=True,
            )
            .add_extension(
                x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
            )
        )
        if not ca:  # C2PA wants a leaf certificate with a signing purpose
            build = build.add_extension(
                x509.ExtendedKeyUsage([ExtendedKeyUsageOID.EMAIL_PROTECTION]), critical=False
            ).add_extension(
                x509.AuthorityKeyIdentifier.from_issuer_public_key(signer.public_key()),
                critical=False,
            )
        return build.sign(signer, hashes.SHA256())

    ca_key, key = ec.generate_private_key(ec.SECP256R1()), ec.generate_private_key(ec.SECP256R1())
    ca = cert("Vinci local C2PA CA", ca_key, None, ca_key, ca=True, days=3650)
    leaf = cert("Vinci OLF export signer", key, ca.subject, ca_key, ca=False, days=825)
    chain = b"".join(c.public_bytes(serialization.Encoding.PEM) for c in (leaf, ca))
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    folder.mkdir(parents=True, exist_ok=True)
    key_path.write_bytes(pem)
    os.chmod(key_path, 0o600)
    chain_path.write_bytes(chain)
    log.info("c2pa: made a local signing certificate in %s", folder)
    return chain, pem


def manifest(p: Project, view: dict[str, Any], title: str) -> dict[str, Any]:
    """The C2PA manifest of one exported file: what made it, and the takes it shows."""
    speech = [
        c["dialogue_take"]["take"]
        for c in view["clips"]
        if c["audio"] == "separate" and c["dialogue_take"]
    ]
    ids = [*(c["take"] for c in view["clips"]), *speech, *(row["take"] for row in view["audio"])]
    takes = []
    for take_id in dict.fromkeys(ids):
        if (doc := p.docs.get(take_id)) is None:
            continue
        made = doc.data.get("provenance") or {}
        terms = (p.lock.get(str(doc.data.get("output"))) or {}).get("license") or {}
        takes.append(
            {
                "id": take_id,
                "model": made.get("model"),
                "provider": made.get("provider"),
                "created": made.get("created"),
                "license": {k: terms[k] for k in ("owner", "terms") if k in terms},
            }
        )
    action = {"action": "c2pa.created", "digitalSourceType": GENERATED}
    olf = {
        "spec": "olf/0.1",
        "show": p.manifest.get("show"),
        "episode": view["episode"],
        "takes": takes,
    }
    return {
        "claim_generator_info": [{"name": "Vinci OLF", "version": "0.1"}],
        "title": title,
        "assertions": [
            {
                "label": "c2pa.actions",
                "data": {"actions": [action | {"softwareAgent": {"name": "Vinci OLF"}}]},
            },
            {"label": "org.tryvinci.olf", "data": olf},
        ],
    }


def sign(path: Path, data: dict[str, Any], home: Path | None = None) -> None:
    """Embed a signed C2PA manifest in an MP4, in place.

    Raises:
        OlfError: ``c2pa-python`` is missing, or signing failed.
    """
    if not available():
        raise OlfError("C2PA needs c2pa-python: pip install 'vinci-olf[c2pa]'")
    import c2pa  # type: ignore[import-untyped]

    if home is None:
        from vinci_core.config import default_home

        home = default_home()
    chain, key = local_signer(home / "c2pa")
    info = c2pa.C2paSignerInfo(alg=b"es256", sign_cert=chain, private_key=key, ta_url=None)
    signed = path.with_name(f"{path.stem}.signing{path.suffix}")
    try:
        c2pa.Builder(data).sign_file(path, signed, c2pa.Signer.from_info(info))
    except c2pa.C2paError as exc:
        signed.unlink(missing_ok=True)
        raise OlfError(f"C2PA signing failed for {path.name}: {exc}") from exc
    signed.replace(path)
    log.info("c2pa: signed %s (%d takes)", path.name, len(data["assertions"][1]["data"]["takes"]))
