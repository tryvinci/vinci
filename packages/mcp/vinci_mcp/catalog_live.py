"""Every model of a Higgsfield or Magnific account, from its free model list (COREPRODUC-669).

The user asked for every model of both providers, by default, on every page (2026-11-16); each
listed 3 hand-picked rows and none took a reference image. This module turns the free lists into
connector rows and prices them with the free previews. ``refresh`` writes ``catalogs/<id>.json``,
which ``connectors`` loads. Nothing here generates or spends.

The lists (read 2026-11-16):

- Higgsfield ``models_explore {action: "list", type: "image"|"video"}``: ``items[]`` with ``id``,
  ``name``, ``medias[].roles`` (``image_references``, ``start_image``, ``end_image``…),
  ``aspect_ratios``, ``parameters[]`` (``duration``, ``resolution`` and ``quality`` options, each
  with a ``default``), ``duration_range`` and ``tags``.
- Magnific ``images_models_list`` and ``video_models_list``, in TOON: ``models[]`` with ``slug``,
  ``name``, ``referenceTypes`` (``image`` means image to image), ``aspectRatios``, ``durations``,
  ``resolutions``, ``supportsStartFrame``, ``supportsEndFrame``, ``supportsReferences`` and
  ``requiredInputs``. It gives no default resolution: an image row takes the first one listed,
  a video row the first of 720p, 768p and 1080p.
"""

from __future__ import annotations

import itertools
import json
import logging
import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from vinci_mcp import toon
from vinci_mcp.connectors import CATALOGS, Connector, Row, parse_cost, payload_from_tool

log = logging.getLogger("vinci.mcp.catalog")

# Tools, not generators: they need a video, audio or a product photo the Image and Video pages do
# not take, or they edit, upscale or cut out an existing file.
TOOLS = re.compile(
    r"background|upscal|topaz|decompose|outpaint|deflicker|dubbing|voice_change|sync|fps_boost|"
    r"depth|sam_3|edit|replace_object|reframe|draw_to_video|image_command|motion.control|marketing|"
    r"ms_image|ad_multiplier|preset|intone|soul_cast|soul_location|3d_jutsu|lipsync|act-two|veed|"
    r"animate|_shots$|omnihuman"
)
LENGTHS = (3, 4, 5, 6, 8, 10, 12, 15)  # the lengths a video row offers, each priced once
REFS = 4  # reference images a row takes (the Studio's limit; both providers take more)
PROMPT = "A red apple on a wooden table, soft daylight"  # the price previews' prompt


def higgsfield_rows(images: list[dict[str, Any]], videos: list[dict[str, Any]]) -> list[Row]:
    """Rows of Higgsfield's image and video lists. A second model with the same name is left out."""
    rows: list[Row] = []
    for item in images + videos:
        model, name = str(item.get("id") or ""), label(str(item.get("name") or ""))
        if not model or not name or TOOLS.search(model):
            continue
        roles = {role for media in item.get("medias") or [] for role in media.get("roles") or []}
        ratios = tuple(r for r in item.get("aspect_ratios") or [] if r != "auto")
        options, defaults = _options(item)
        if item.get("output_type") == "video":
            tags = set(item.get("tags") or [])
            only_image = "image-to-video" in tags and "text-to-video" not in tags
            caps = (() if only_image else ("t2v",)) + (("i2v",) if "start_image" in roles else ())
            if not caps:
                continue
            rows.append(
                Row(
                    model,
                    name,
                    "i2v" if "i2v" in caps else "t2v",
                    None,
                    ratios,
                    settings=defaults,
                    caps=caps,
                    durations=_lengths(item),
                    end_frame="end_image" in roles,
                    refs=REFS if "image_references" in roles else 0,
                    ref_role="image_references",
                    options=options,
                )
            )
        else:
            ref_role = next((r for r in ("image_references", "image") if r in roles), "")
            if roles - {
                "image_references",
                "image",
                "mask",
                "video_references",
                "audio_references",
            }:
                continue  # a product, character or location input the Image page does not take
            caps = ("t2i", "i2i") if ref_role else ("t2i",)
            rows.append(
                Row(
                    model,
                    name,
                    "t2i",
                    None,
                    ratios,
                    settings=defaults,
                    caps=caps,
                    refs=REFS if ref_role else 0,
                    ref_role=ref_role,
                    options=options,
                )
            )
    return _unique(rows)


def magnific_rows(images: list[dict[str, Any]], videos: list[dict[str, Any]]) -> list[Row]:
    """Rows of Magnific's image and video lists. A video model that needs more than a prompt (lip
    sync, character animation) or has no lengths is left out."""
    rows: list[Row] = []
    for item in images:
        model, name = str(item.get("slug") or ""), str(item.get("name") or "")
        if not model or not name or TOOLS.search(model):
            continue
        refs = REFS if "image" in (item.get("referenceTypes") or []) else 0
        caps = ("t2i", "i2i") if refs else ("t2i",)
        ratios = tuple(r for r in item.get("aspectRatios") or [] if r != "auto")
        listed = tuple(str(r) for r in item.get("resolutions") or [])
        rows.append(
            Row(
                model,
                name,
                "t2i",
                None,
                ratios,
                settings=(("resolution", listed[0]),) if listed else (),
                caps=caps,
                refs=refs,
                options=(("resolution", listed),) if listed else (),
            )
        )
    for item in videos:
        model, name = str(item.get("slug") or ""), str(item.get("name") or "")
        lengths = [int(n) for n in item.get("durations") or [] if isinstance(n, int | float)]
        if (
            not model
            or not lengths
            or TOOLS.search(model)
            or "prompt" not in (item.get("requiredInputs") or [])
        ):
            continue
        picks = tuple(n for n in LENGTHS if n in lengths) or (lengths[0],)
        sizes = [str(r) for r in item.get("resolutions") or []]
        size = next((r for r in ("720p", "768p", "1080p") if r in sizes), sizes[0] if sizes else "")
        caps = ("t2v", "i2v") if item.get("supportsStartFrame") else ("t2v",)
        rows.append(
            Row(
                model,
                name,
                "i2v" if "i2v" in caps else "t2v",
                None,
                tuple(r for r in item.get("aspectRatios") or [] if r != "auto"),
                settings=(("resolution", size),) if size else (),
                caps=caps,
                durations=picks,
                end_frame=bool(item.get("supportsEndFrame")),
                refs=REFS if item.get("supportsReferences") else 0,
                options=(("resolution", tuple(sizes)),) if sizes else (),
            )
        )
    return _unique(rows)


def price_rows(
    connector: Connector, rows: list[Row], call: Callable[[str, dict[str, Any]], Any]
) -> list[Row]:
    """Each row with its price from the provider's free preview: one per offered length and option.

    The default options give the row's price and clip prices; every option set gives an
    ``option_credits`` entry. A row whose preview fails (it needs a start frame, or the provider
    refuses the settings) keeps no price; the Studio shows "price varies" and a run checks nothing
    against it. An option set whose preview fails has no entry: a run of it is checked against the
    default price, and stops before any spend when it costs more.
    """
    priced = []
    for row in rows:
        clips: list[tuple[int, float]] = []
        options: dict[str, float] = {}
        defaults = row.picks({})
        for length in row.durations or (None,):
            for picks in _option_sets(row):
                inputs = {"prompt": PROMPT, "duration": length, **picks}
                args = connector.arguments(row, inputs)
                tool, preview = connector.cost_call(connector.tools[row.capability], args)
                try:
                    cost = parse_cost(call(tool, preview))
                except Exception as exc:  # noqa: BLE001 — an unpriced row is still listed
                    log.info(
                        "catalog price failed provider=%s model=%s length=%s picks=%s error=%s",
                        connector.id,
                        row.model,
                        length,
                        picks,
                        str(exc)[:160],
                    )
                    cost = None
                if cost is None:
                    continue
                if row.options:
                    options[row.option_key(length, row.picks(picks))] = cost
                if row.picks(picks) == defaults:
                    clips.append((length or 0, cost))
        if not clips:  # the default stays unpriced; the option sets that were priced stay
            priced.append(replace(row, option_credits=tuple(options.items())))
            continue
        credits = clips[0][1]
        table = tuple(c for c in clips if c[0]) if row.durations else ()
        # Only the lengths with a price are offered, so a run's check always has one.
        priced.append(
            replace(
                row,
                credits=credits,
                clip_credits=table,
                durations=tuple(n for n, _ in table) or row.durations,
                option_credits=tuple(options.items()),
            )
        )
        log.info(
            "catalog priced provider=%s model=%s credits=%s clips=%s options=%s",
            connector.id,
            row.model,
            credits,
            len(table),
            len(options),
        )
    return priced


def refresh(connector: Connector, call: Callable[[str, dict[str, Any]], Any]) -> dict[str, Any]:
    """Read the provider's model lists, price every row, and write ``catalogs/<id>.json``.

    Args:
        connector: Higgsfield or Magnific.
        call: ``call(tool, arguments)`` on a signed-in session; it must answer the free list and
            price tools only.

    Returns:
        The snapshot: ``{"provider", "listed_at", "rows": [...]}``.
    """
    if connector.id == "mcp_higgsfield":
        lists = [
            payload_from_tool(
                call("models_explore", {"action": "list", "type": kind, "limit": 100})
            ).get("items")
            or []
            for kind in ("image", "video")
        ]
        rows = higgsfield_rows(*lists)
    else:
        lists = [
            _toon_models(call(tool, {})) for tool in ("images_models_list", "video_models_list")
        ]
        rows = magnific_rows(*lists)
    rows = price_rows(connector, rows, call)
    snapshot = {
        "provider": connector.id,
        "listed_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "rows": [_row_json(row) for row in rows],
    }
    CATALOGS.mkdir(exist_ok=True)
    (CATALOGS / f"{connector.id}.json").write_text(
        json.dumps(snapshot, indent=1) + "\n", encoding="utf-8"
    )
    log.info(
        "catalog written provider=%s rows=%s priced=%s",
        connector.id,
        len(rows),
        sum(r.credits is not None for r in rows),
    )
    return snapshot


def _lengths(item: dict[str, Any]) -> tuple[int, ...]:
    """A Higgsfield video's offered lengths: its ``duration`` options, else ``duration_range``."""
    for param in item.get("parameters") or []:
        if param.get("name") == "duration" and param.get("options"):
            options = [int(n) for n in param["options"] if isinstance(n, int | float)]
            return tuple(n for n in LENGTHS if n in options) or tuple(options[:1])
    span = item.get("duration_range") or {}
    low, high = span.get("min"), span.get("max")
    if isinstance(low, int | float) and isinstance(high, int | float):
        return tuple(n for n in LENGTHS if low <= n <= high)
    return ()


def _options(
    item: dict[str, Any],
) -> tuple[tuple[tuple[str, tuple[str, ...]], ...], tuple[tuple[str, str], ...]]:
    """A Higgsfield model's ``resolution`` and ``quality`` options, and their defaults.

    Returns:
        ``(options, settings)``: ``((name, values), ...)`` in the provider's order, and
        ``((name, default), ...)``: the listed default, else the first value.
    """
    options: list[tuple[str, tuple[str, ...]]] = []
    settings: list[tuple[str, str]] = []
    params = {p.get("name"): p for p in item.get("parameters") or [] if isinstance(p, dict)}
    for name in ("resolution", "quality"):
        values = tuple(str(v) for v in (params.get(name) or {}).get("options") or [])
        if not values:
            continue
        default = str(params[name].get("default") or "")
        options.append((name, values))
        settings.append((name, default if default in values else values[0]))
    return tuple(options), tuple(settings)


def _option_sets(row: Row) -> list[dict[str, str]]:
    """Every set of option values a row offers, the default set first (none: one empty set)."""
    names = [name for name, _ in row.options]
    every = itertools.product(*(values for _, values in row.options))
    sets = [dict(zip(names, values, strict=True)) for values in every]
    defaults = row.picks({})
    return sorted(sets, key=lambda picks: picks != defaults)


def label(name: str) -> str:
    """A list name as people read it: a raw id such as ``soul_cinema_studio`` becomes
    "Soul Cinema Studio" (Higgsfield lists a few that way)."""
    if " " in name or "_" not in name:
        return name
    return " ".join(part.capitalize() for part in name.split("_"))


def _unique(rows: list[Row]) -> list[Row]:
    seen: set[str] = set()
    out = []
    for row in rows:
        if row.label.lower() not in seen:
            seen.add(row.label.lower())
            out.append(row)
    return out


def _toon_models(result: Any) -> list[dict[str, Any]]:
    payload = payload_from_tool(result)
    if not isinstance(payload, dict) or "models" not in payload:
        text = "\n".join(
            b.get("text", "") for b in (result or {}).get("content") or [] if isinstance(b, dict)
        )
        payload = toon.loads(text) if text else {}
    models = payload.get("models") if isinstance(payload, dict) else None
    return [m for m in models or [] if isinstance(m, dict)]


def _row_json(row: Row) -> dict[str, Any]:
    out: dict[str, Any] = {
        "model": row.model,
        "label": row.label,
        "capability": row.capability,
        "credits": row.credits,
        "caps": list(row.capabilities),
    }
    out |= {"ratios": list(row.ratios)} if row.ratios else {}
    out |= {"settings": dict(row.settings)} if row.settings else {}
    out |= {"durations": list(row.durations)} if row.durations else {}
    out |= {"clip_credits": {str(n): c for n, c in row.clip_credits}} if row.clip_credits else {}
    out |= {"end_frame": True} if row.end_frame else {}
    out |= {"refs": row.refs} if row.refs else {}
    out |= {"ref_role": row.ref_role} if row.ref_role else {}
    out |= {"options": {k: list(v) for k, v in row.options}} if row.options else {}
    out |= {"option_credits": dict(row.option_credits)} if row.option_credits else {}
    return out
