"""Batch renders for an episode: re-render what went stale, animate approved keyframes, or
draw first keyframes (design: New show, "Create show and draw keyframes").

A batch plans every render first and checks the price once, for the whole batch. Then it runs
the renders in play order, one shot after another (``vinci_olf.render.render`` for each).
The engine never writes ``select``: a new keyframe waits for a person to choose it.
"""

from __future__ import annotations

import logging
from typing import Any

from vinci_olf.cut import play_order, takes
from vinci_olf.project import OlfError, Project, load
from vinci_olf.render import render
from vinci_olf.resolve import from_keyframe, resolve, stale

log = logging.getLogger(__name__)
MODES = ("stale", "animate", "keyframes")
KEYFRAME_OPTIONS = 2  # keyframes a "keyframes" batch draws per shot (design: 2 options per shot)


def jobs(p: Project, episode_id: str, mode: str) -> list[dict[str, Any]]:
    """Return the renders a batch runs, in play order: ``[{"shot", "kind", "why"}]``.

    ``stale``: each kind (keyframe, video, audio) whose current take (the selected one, else the
    newest) is stale, when no fresh take of that kind waits beside it. A video waits while the
    chosen keyframe it animates from is stale too: the new keyframe needs a person's choice.
    ``animate``: a video for each shot whose chosen keyframe is approved and fresh, when no fresh
    video was made from it. ``keyframes``: two keyframes for each shot that has none yet.

    A shot that does not resolve gets ``{"shot", "kind": None, "error"}`` and is not rendered.

    Raises:
        OlfError: The mode is unknown, or the episode does not exist.
    """
    if mode not in MODES:
        raise OlfError(f"mode must be one of {', '.join(MODES)}, not {mode!r}")
    cache: dict[str, dict[str, Any]] = {}
    out: list[dict[str, Any]] = []
    for shot_id in play_order(p, episode_id):
        try:
            view = cache.setdefault(shot_id, resolve(p, shot_id))
        except OlfError as exc:
            out.append({"shot": shot_id, "kind": None, "error": str(exc)})
            continue
        if mode == "keyframes":
            if not takes(p, shot_id, "keyframe"):
                out.append(
                    {
                        "shot": shot_id,
                        "kind": "keyframe",
                        "count": KEYFRAME_OPTIONS,
                        "why": "no keyframe yet",
                    }
                )
            continue
        select = view.get("select") or {}
        keyframe = f"{shot_id}/{select['keyframe']}" if select.get("keyframe") else None
        keyframe_ok = keyframe in p.docs and not stale(p, str(keyframe), cache)
        animates = from_keyframe(view)
        if mode == "animate":
            approved = keyframe_ok and p.docs[str(keyframe)].data.get("status") == "approved"
            made = [
                v
                for v in takes(p, shot_id, "video")
                if (p.docs[v].data.get("inputs") or {}).get("first_frame") == keyframe
                and not stale(p, v, cache)
            ]
            if animates and approved and not made:
                out.append(
                    {"shot": shot_id, "kind": "video", "why": f"animate {select['keyframe']}"}
                )
            continue
        for kind in ("keyframe", "video", "audio"):
            rows = takes(p, shot_id, kind)
            picked = f"{shot_id}/{select[kind]}" if select.get(kind) else None
            current = picked if picked in rows else (rows[-1] if rows else None)
            if current is None or not stale(p, current, cache):
                continue
            if any(not stale(p, take, cache) for take in rows):
                continue  # a fresh take waits for a person to choose it
            if kind == "video" and animates and not keyframe_ok:
                continue  # the video waits for a fresh chosen keyframe
            if kind == "audio" and not view.get("dialogue"):
                continue  # the dialogue is gone: nothing to speak
            name = current.rsplit("/", 1)[1]
            out.append({"shot": shot_id, "kind": kind, "why": f"{name} is stale"})
    return out


def render_batch(
    p: Project,
    episode_id: str,
    *,
    mode: str,
    yes: bool = False,
    max_total: float | None = None,
    dry_run: bool = False,
    engine: Any = None,
) -> dict[str, Any]:
    """Plan a batch, check its price once, then (unless ``dry_run``) run it in play order.

    A render that fails is reported on its job; the other renders still run. Each job loads the
    project again, so it sees the takes the jobs before it wrote, and it may not cost more than
    its planned price.

    Args:
        p: The loaded project.
        episode_id: The episode, for example ``e02``.
        mode: ``stale``, ``animate`` or ``keyframes`` (see ``jobs``).
        yes: Allow a batch that costs money. Without it, a paid batch stops before it runs.
        max_total: The total a person confirmed (Studio). A plan above it stops.
        dry_run: Return the jobs and prices only. Nothing runs or is written.
        engine: A ``vinci_runtime.engine.Engine``. Default: the one for ``$VINCI_HOME``.

    Returns:
        ``{"mode", "jobs": [{"shot", "kind", "why", "plan", "total", "takes", "error"}],
        "total": USD, "unpriced": [model IDs], "takes": [new take IDs]}``.

    Raises:
        OlfError: The mode or episode is wrong, or the batch costs money and ``yes`` is False.
    """
    if engine is None:
        from vinci_runtime.engine import Engine

        engine = Engine()
    todo = jobs(p, episode_id, mode)
    for job in (job for job in todo if not job.get("error")):
        try:
            count = job.get("count", 1)
            plan = render(
                p, job["shot"], kind=job["kind"], count=count, dry_run=True, engine=engine
            )
            job |= {"plan": plan["plan"], "total": plan["total"], "unpriced": plan["unpriced"]}
        except OlfError as exc:
            job["error"] = str(exc)
    ready = [job for job in todo if not job.get("error")]
    total = sum(job["total"] for job in ready)
    unpriced = sorted({model for job in ready for model in job["unpriced"]})
    result: dict[str, Any] = {
        "mode": mode,
        "jobs": todo,
        "total": total,
        "unpriced": unpriced,
        "takes": [],
    }
    log.info(
        "batch %s %s: %d renders, $%.2f (%d not possible)",
        episode_id,
        mode,
        len(ready),
        total,
        len(todo) - len(ready),
    )
    if dry_run or not ready:
        return result
    if max_total is not None and total > max_total + 1e-9:
        raise OlfError(
            f"the price changed: this batch costs ${total:.2f}, more than the ${max_total:.2f} "
            "you confirmed. Check the price again"
        )
    if (total > 0 or unpriced) and not yes:
        extra = f", plus {', '.join(unpriced)} with no flat price" if unpriced else ""
        renders = f"{len(ready)} render" + ("s" if len(ready) > 1 else "")
        raise OlfError(
            f"this batch costs ${total:.2f}{extra} for {renders}. Run again with --yes to spend it"
        )
    for job in ready:  # synchronous: one shot after another, in play order
        try:
            fresh = load(p.root)  # sees the takes and lock entries the jobs before it wrote
            done = render(
                fresh,
                job["shot"],
                kind=job["kind"],
                count=job.get("count", 1),
                yes=True,
                max_total=job["total"],
                engine=engine,
            )
            job["takes"] = done["takes"]
        except OlfError as exc:
            job["error"] = str(exc)
            log.warning("batch %s: %s %s failed: %s", episode_id, job["shot"], job["kind"], exc)
    result["takes"] = [take for job in ready for take in job.get("takes") or []]
    return result
