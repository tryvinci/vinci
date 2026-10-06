"""Client-partner export specs (Axis Max Life PDF pages 3, 4, 6, 7).

These are client_partner specs, not general platform rules. Human-review advisories
are labeled and are not treated as automated compliance checks.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

ByteCapOp = Literal["lte", "lt"]  # lte = at/over inclusive cap; lt = strictly below


@dataclass(frozen=True)
class ByteCap:
    max_bytes: int
    op: ByteCapOp = "lte"


@dataclass(frozen=True)
class SafeRectMarginsPx:
    """Content-safe rectangle via pixel margins from each edge."""

    left: int
    right: int
    top: int
    bottom: int


@dataclass(frozen=True)
class PartnerAdaptPreset:
    id: str
    label: str
    partner: str
    width: int
    height: int
    spec_kind: str = "client_partner"
    byte_cap: ByteCap | None = None
    safe_rect_margins_px: SafeRectMarginsPx | None = None
    export_mime: tuple[str, ...] = ("image/png",)
    human_review_advisories: tuple[str, ...] = ()


META_DISCLAIMER = (
    "Company Name Axis Max Life Insurance Limited | Axis Max Life Smart Term Plan Plus "
    "UIN 104N127V04 | IRDAI Reg No 104 | ARN | total premium ... | Brand Ambassador "
    "endorses only Axis Max Life products, not Axis Bank | *T&C Apply."
)

AMAZON_DISCLAIMER = ("Disclaimer 8-11pt, white background good.",)

BPN_SHORT_DISCLAIMER = "IRDAI Regn No. 104 | ARN | *T&C Apply"


PARTNER_ADAPT_PRESETS: tuple[PartnerAdaptPreset, ...] = (
    PartnerAdaptPreset(
        id="amazon_828x300",
        label="Amazon 828×300",
        partner="amazon",
        width=828,
        height=300,
        byte_cap=ByteCap(100 * 1024, "lte"),
        safe_rect_margins_px=SafeRectMarginsPx(left=94, right=94, top=0, bottom=0),
        human_review_advisories=AMAZON_DISCLAIMER,
    ),
    PartnerAdaptPreset(
        id="amazon_828x250",
        label="Amazon 828×250",
        partner="amazon",
        width=828,
        height=250,
        byte_cap=ByteCap(100 * 1024, "lte"),
        safe_rect_margins_px=SafeRectMarginsPx(left=94, right=94, top=0, bottom=0),
        human_review_advisories=AMAZON_DISCLAIMER,
    ),
    PartnerAdaptPreset(
        id="amazon_600x500",
        label="Amazon 600×500",
        partner="amazon",
        width=600,
        height=500,
        byte_cap=ByteCap(150 * 1024, "lte"),
        human_review_advisories=AMAZON_DISCLAIMER,
    ),
    PartnerAdaptPreset(
        id="amazon_640x100",
        label="Amazon 640×100",
        partner="amazon",
        width=640,
        height=100,
        byte_cap=ByteCap(20 * 1024, "lte"),
        human_review_advisories=AMAZON_DISCLAIMER,
    ),
    PartnerAdaptPreset(
        id="inuxu_1200x720",
        label="Inuxu 1200×720",
        partner="inuxu",
        width=1200,
        height=720,
        byte_cap=ByteCap(300 * 1024, "lte"),
        safe_rect_margins_px=SafeRectMarginsPx(left=175, right=175, top=110, bottom=110),
    ),
    PartnerAdaptPreset(
        id="inuxu_728x90",
        label="Inuxu 728×90",
        partner="inuxu",
        width=728,
        height=90,
        byte_cap=ByteCap(300 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="inuxu_320x50",
        label="Inuxu 320×50",
        partner="inuxu",
        width=320,
        height=50,
        byte_cap=ByteCap(300 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="jio_ldpi_216x117",
        label="Jio LDPI 216×117",
        partner="jio",
        width=216,
        height=117,
        byte_cap=ByteCap(10 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="jio_mdpi_288x156",
        label="Jio MDPI 288×156",
        partner="jio",
        width=288,
        height=156,
        byte_cap=ByteCap(12 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="jio_hdpi_432x234",
        label="Jio HDPI 432×234",
        partner="jio",
        width=432,
        height=234,
        byte_cap=ByteCap(15 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="jio_xhdpi_576x312",
        label="Jio XHDPI 576×312",
        partner="jio",
        width=576,
        height=312,
        byte_cap=ByteCap(18 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="jio_xxhdpi_864x468",
        label="Jio XXHDPI 864×468",
        partner="jio",
        width=864,
        height=468,
        byte_cap=ByteCap(20 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="jio_xxxhdpi_1152x624",
        label="Jio XXXHDPI 1152×624",
        partner="jio",
        width=1152,
        height=624,
        byte_cap=ByteCap(25 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="jio_1200x627",
        label="Jio 1200×627 (JPEG/PNG)",
        partner="jio",
        width=1200,
        height=627,
        byte_cap=ByteCap(200 * 1024, "lt"),
        export_mime=("image/png", "image/jpeg"),
    ),
    PartnerAdaptPreset(
        id="jio_320x50",
        label="Jio 320×50",
        partner="jio",
        width=320,
        height=50,
        byte_cap=None,
    ),
    PartnerAdaptPreset(
        id="jio_1274x546",
        label="Jio 1274×546",
        partner="jio",
        width=1274,
        height=546,
        byte_cap=None,
    ),
    PartnerAdaptPreset(
        id="jio_1440x448",
        label="Jio 1440×448",
        partner="jio",
        width=1440,
        height=448,
        byte_cap=None,
    ),
    PartnerAdaptPreset(
        id="meta_google_1200x1200",
        label="Meta Google 1200×1200",
        partner="meta",
        width=1200,
        height=1200,
        byte_cap=ByteCap(150 * 1024, "lte"),
        human_review_advisories=(META_DISCLAIMER,),
    ),
    PartnerAdaptPreset(
        id="meta_1080x1920",
        label="Meta 1080×1920",
        partner="meta",
        width=1080,
        height=1920,
        byte_cap=ByteCap(250 * 1024, "lte"),
        human_review_advisories=(META_DISCLAIMER,),
    ),
    PartnerAdaptPreset(
        id="meta_1200x630",
        label="Meta 1200×630",
        partner="meta",
        width=1200,
        height=630,
        byte_cap=ByteCap(250 * 1024, "lte"),
        human_review_advisories=(META_DISCLAIMER,),
    ),
    PartnerAdaptPreset(
        id="meta_960x1200",
        label="Meta 960×1200",
        partner="meta",
        width=960,
        height=1200,
        byte_cap=ByteCap(250 * 1024, "lte"),
        human_review_advisories=(META_DISCLAIMER,),
    ),
    PartnerAdaptPreset(
        id="paytm_1440x720",
        label="Paytm 1440×720",
        partner="paytm",
        width=1440,
        height=720,
        byte_cap=None,
    ),
    PartnerAdaptPreset(
        id="paytm_1440x480",
        label="Paytm 1440×480",
        partner="paytm",
        width=1440,
        height=480,
        byte_cap=None,
    ),
    PartnerAdaptPreset(
        id="paytm_1440x864",
        label="Paytm 1440×864",
        partner="paytm",
        width=1440,
        height=864,
        byte_cap=None,
    ),
    PartnerAdaptPreset(
        id="paytm_1440x404",
        label="Paytm 1440×404",
        partner="paytm",
        width=1440,
        height=404,
        byte_cap=None,
    ),
    PartnerAdaptPreset(
        id="paytm_1440x448",
        label="Paytm 1440×448",
        partner="paytm",
        width=1440,
        height=448,
        byte_cap=None,
    ),
    PartnerAdaptPreset(
        id="paytm_1274x546",
        label="Paytm 1274×546",
        partner="paytm",
        width=1274,
        height=546,
        byte_cap=None,
    ),
    PartnerAdaptPreset(
        id="paytm_logo_640x640",
        label="Paytm logo 640×640",
        partner="paytm",
        width=640,
        height=640,
        byte_cap=ByteCap(1024 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="indixital_300x250",
        label="Indixital 300×250",
        partner="indixital",
        width=300,
        height=250,
        byte_cap=ByteCap(200 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="indixital_728x90",
        label="Indixital 728×90",
        partner="indixital",
        width=728,
        height=90,
        byte_cap=ByteCap(200 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="indixital_320x100",
        label="Indixital 320×100",
        partner="indixital",
        width=320,
        height=100,
        byte_cap=ByteCap(200 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="indixital_300x100",
        label="Indixital 300×100",
        partner="indixital",
        width=300,
        height=100,
        byte_cap=ByteCap(200 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="indixital_300x50",
        label="Indixital 300×50",
        partner="indixital",
        width=300,
        height=50,
        byte_cap=ByteCap(200 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="indixital_320x50",
        label="Indixital 320×50",
        partner="indixital",
        width=320,
        height=50,
        byte_cap=ByteCap(200 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="indixital_1200x720",
        label="Indixital 1200×720",
        partner="indixital",
        width=1200,
        height=720,
        byte_cap=ByteCap(200 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="indixital_1500x750",
        label="Indixital 1500×750",
        partner="indixital",
        width=1500,
        height=750,
        byte_cap=ByteCap(200 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="indixital_360x180",
        label="Indixital 360×180",
        partner="indixital",
        width=360,
        height=180,
        byte_cap=ByteCap(200 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="indixital_logo_100x100",
        label="Indixital logo 100×100",
        partner="indixital",
        width=100,
        height=100,
        byte_cap=ByteCap(200 * 1024, "lte"),
    ),
    PartnerAdaptPreset(
        id="chase_whatsapp_1080x566",
        label="CHASE WhatsApp 1080×566",
        partner="chase",
        width=1080,
        height=566,
        byte_cap=ByteCap(550 * 1024, "lt"),
        human_review_advisories=("No CTA.", "No logos."),
    ),
    PartnerAdaptPreset(
        id="bpn_360x180",
        label="CHASE BPN 360×180",
        partner="bpn",
        width=360,
        height=180,
        byte_cap=ByteCap(40 * 1024, "lt"),
        human_review_advisories=(
            "No logos.",
            "CTA Buy Now.",
            BPN_SHORT_DISCLAIMER,
        ),
    ),
    PartnerAdaptPreset(
        id="meta_1440x480",
        label="CHASE RCS 1440×480",
        partner="chase",
        width=1440,
        height=480,
        byte_cap=ByteCap(2 * 1024 * 1024, "lte"),
        human_review_advisories=(
            "Ratio 3:4.",
            "IN UNIT LINKED POLICIES THE INVESTMENT RISK IN THE INVESTMENT PORTFOLIO IS "
            "BORNE BY THE POLICYHOLDER",
            "IRDAI Regn No. 104 | ARN | *T&C Apply",
            "No AMLI logo.",
            "No CTA.",
        ),
    ),
    PartnerAdaptPreset(
        id="cred_1000x1000",
        label="CRED 1000×1000",
        partner="cred",
        width=1000,
        height=1000,
        byte_cap=None,
    ),
    PartnerAdaptPreset(
        id="cred_cheque_121x327",
        label="CRED cheque 121×327",
        partner="cred",
        width=121,
        height=327,
        byte_cap=None,
    ),
    PartnerAdaptPreset(
        id="cred_cheque_396x375",
        label="CRED cheque 396×375",
        partner="cred",
        width=396,
        height=375,
        byte_cap=None,
    ),
    PartnerAdaptPreset(
        id="chase_cs_homepage_960x1080",
        label="CHASE CS homepage 960×1080",
        partner="chase",
        width=960,
        height=1080,
        byte_cap=ByteCap(350 * 1024, "lte"),
        human_review_advisories=("CTA left aligned logo.",),
    ),
    PartnerAdaptPreset(
        id="chase_cs_dashboard_mobile_1312x726",
        label="CHASE CS dashboard mobile 1312×726",
        partner="chase",
        width=1312,
        height=726,
        byte_cap=None,
        human_review_advisories=("CTA no logo.",),
    ),
    PartnerAdaptPreset(
        id="chase_cs_dashboard_desktop_688x224",
        label="CHASE CS dashboard desktop 688×224",
        partner="chase",
        width=688,
        height=224,
        byte_cap=ByteCap(100 * 1024, "lte"),
        human_review_advisories=("CTA no logo.",),
    ),
    PartnerAdaptPreset(
        id="chase_pay_online_web_528x513",
        label="CHASE pay online web 528×513",
        partner="chase",
        width=528,
        height=513,
        byte_cap=None,
        human_review_advisories=("No logo.",),
    ),
    PartnerAdaptPreset(
        id="chase_pay_online_mobile_360x244",
        label="CHASE pay online mobile 360×244",
        partner="chase",
        width=360,
        height=244,
        byte_cap=None,
        human_review_advisories=("No logo.",),
    ),
)


def partner_preset_by_id(preset_id: str) -> PartnerAdaptPreset | None:
    for preset in PARTNER_ADAPT_PRESETS:
        if preset.id == preset_id:
            return preset
    return None


def byte_cap_document(cap: ByteCap | None) -> dict[str, Any] | None:
    if cap is None:
        return None
    return {
        "max_bytes": cap.max_bytes,
        "op": cap.op,
        "semantics": "lte" if cap.op == "lte" else "strictly_below",
    }


def partner_preset_document(preset: PartnerAdaptPreset) -> dict[str, Any]:
    safe: dict[str, Any] | None = None
    if preset.safe_rect_margins_px is not None:
        m = preset.safe_rect_margins_px
        safe = {
            "kind": "margins_px",
            "left": m.left,
            "right": m.right,
            "top": m.top,
            "bottom": m.bottom,
            "content_width": preset.width - m.left - m.right,
            "content_height": preset.height - m.top - m.bottom,
        }
    return {
        "id": preset.id,
        "label": preset.label,
        "partner": preset.partner,
        "platform": preset.partner,
        "spec_kind": preset.spec_kind,
        "width": preset.width,
        "height": preset.height,
        "export_validation": {
            "dimensions": {"width": preset.width, "height": preset.height},
            "byte_cap": byte_cap_document(preset.byte_cap),
            "mime_allowlist": list(preset.export_mime),
            "generic_source_cap_bytes": 20 * 1024 * 1024,
        },
        "safe_rect": safe,
        "human_review_advisories": list(preset.human_review_advisories),
        "automated_checks": _automated_check_labels(preset),
    }


def _automated_check_labels(preset: PartnerAdaptPreset) -> list[str]:
    checks = ["export_dimensions", "export_file_bytes"]
    if preset.byte_cap is not None:
        checks.append("export_byte_cap")
    if preset.safe_rect_margins_px is not None:
        checks.append("safe_rect_overlay")
    return checks


def partner_presets_document() -> list[dict[str, Any]]:
    return [partner_preset_document(p) for p in PARTNER_ADAPT_PRESETS]


def check_export_bytes(size: int, cap: ByteCap) -> bool:
    if cap.op == "lte":
        return size <= cap.max_bytes
    return size < cap.max_bytes
