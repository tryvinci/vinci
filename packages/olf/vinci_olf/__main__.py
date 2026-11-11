"""CLI for the OLF movie engine: ``python -m vinci_olf`` (also ``./scripts/vinci olf``)."""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from vinci_olf.project import OlfError, Project, load, write
from vinci_olf.resolve import awaits_keyframe, hash_view, inputs_hash, resolve, stale, take_frames
from vinci_olf.validate import validate


def _validate(p: Project, args: argparse.Namespace) -> int:
    issues = validate(p)
    for issue in issues:
        print(issue)
    errors = sum(i.level == "error" for i in issues)
    verdict = "ok" if not errors else "invalid"
    print(f"{verdict}: {errors} errors, {len(issues) - errors} warnings, {len(p.docs)} objects")
    return 1 if errors else 0


def _resolve(p: Project, args: argparse.Namespace) -> int:
    """Print the resolved shot (or its hash view for ``--kind``) and the inputs hash of each
    kind; a video that waits for a chosen keyframe says so in place of a hash."""
    view = resolve(p, args.shot)
    picked = (view.get("select") or {}).get("keyframe")
    frames = take_frames(p, {"inputs": {"first_frame": f"{args.shot}/{picked}"}}) if picked else {}
    write(hash_view(view, args.kind, frames) if args.kind else view, sys.stdout)
    waits = awaits_keyframe(view, frames)  # also an engine move with no chosen keyframe
    for kind in [args.kind] if args.kind else ["keyframe", "video"]:
        value = (
            "needs a selected keyframe (select.keyframe)"
            if kind == "video" and waits
            else inputs_hash(view, kind, frames)
        )
        print(f"# inputs_hash ({kind}): {value}")
    return 0


def _status(p: Project, args: argparse.Namespace) -> int:
    cache: dict[str, Any] = {}
    takes = [k for k in p.docs if p.kind(k) == "take" and k.startswith(args.prefix)]
    for take_id in takes:
        take, is_stale = p.docs[take_id].data, stale(p, take_id, cache)
        state = "n/a" if is_stale is None else "stale" if is_stale else "fresh"
        print(f"{take_id:<28} {take.get('kind', '?'):<9} {take.get('status', '?'):<10} {state}")
    print(f"{len(takes)} takes")
    return 0


def _render(p: Project, args: argparse.Namespace) -> int:
    """Render a shot or an episode cue (``/cue/`` in the ID): print the plan, the price, the
    notes and the takes it wrote. Money moves only with ``--yes``."""
    from vinci_olf.render import render

    if "/cue/" in args.shot:  # a music or SFX cue of the episode
        from vinci_olf.cues import render_cue

        result = render_cue(p, args.shot, model=args.model, yes=args.yes, dry_run=args.dry_run)
    else:
        kw = {"kind": args.kind, "model": args.model, "keyframe_model": args.keyframe_model}
        kw["count"] = args.count
        result = render(p, args.shot, yes=args.yes, dry_run=args.dry_run, **kw)
    for row in result["plan"]:
        added = f"  + extensions: {', '.join(row['extensions'])}" if row.get("extensions") else ""
        print(f"plan  {row['node']:<9} {row['model']:<28} ${row['amount']:.2f}{added}")
    print(f"total ${result['total']:.2f}" + ("  (dry run: nothing ran)" if args.dry_run else ""))
    if result["unpriced"]:
        print(f"no flat price: {', '.join(result['unpriced'])} (needs --yes)")
    for note in result.get("notes") or []:  # for example an engine move that enlarges its keyframe
        print(f"note  {note}")
    for take_id in result["takes"]:
        print(f"wrote takes/{take_id}.yaml")
    return 0


def _batch(p: Project, args: argparse.Namespace) -> int:
    from vinci_olf.batch import render_batch

    mode = "stale" if args.stale else "animate"
    result = render_batch(p, args.episode, mode=mode, yes=args.yes, dry_run=args.dry_run)
    for job in result["jobs"]:
        price = f"${job['total']:.2f}" if "total" in job else ""
        done = job.get("error") or ", ".join(job.get("takes") or []) or job.get("why", "")
        print(f"{job['shot']:<16} {job['kind'] or '-':<9} {price:>6}  {done}")
    ok = sum(not job.get("error") for job in result["jobs"])  # failed and impossible jobs have one
    note = "  (dry run: nothing ran)" if args.dry_run else ""
    print(f"{ok} {'render' if ok == 1 else 'renders'}, total ${result['total']:.2f}{note}")
    if result["unpriced"]:
        print(f"no flat price: {', '.join(result['unpriced'])} (needs --yes)")
    return 0


def _review(p: Project, args: argparse.Namespace) -> int:
    from vinci_olf.edit import set_take

    take = set_take(p, args.take, status=args.status, notes=args.notes)
    print(
        f"{args.take}: {take.get('status')}" + (f" ({take['notes']})" if take.get("notes") else "")
    )
    return 0


def _select(p: Project, args: argparse.Namespace) -> int:
    from vinci_olf.edit import set_select

    picks = {k: getattr(args, k) for k in ("keyframe", "video", "audio") if getattr(args, k)}
    picks = {k: None if v == "none" else v for k, v in picks.items()}
    print(f"{args.shot}: select {set_select(p, args.shot, **picks)}")
    return 0


def _cut(p: Project, args: argparse.Namespace) -> int:
    from vinci_olf.cut import cut_view, use_approved

    if args.use_approved:
        use_approved(p, args.episode)
    view = cut_view(p, args.episode)
    for clip in view["clips"]:
        state = "missing" if clip["missing"] else "stale" if clip["stale"] else "fresh"
        print(
            f"{clip['start']:7.2f}s  {clip['take']:<24} {clip['kind']:<8} "
            f"{clip['in']:g}-{clip['out']:g}s  {clip['transition']:<4}  {state}"
        )
    print(
        f"{len(view['clips'])} clips, {view['duration']:.2f} s"
        + (f", {view['stale']} stale" if view["stale"] else "")
    )
    return 0


def _export(p: Project, args: argparse.Namespace) -> int:
    """Export the cut of an episode: one MP4 for each aspect, with subtitles and sound."""
    from vinci_olf.export import export

    aspects = tuple(args.aspect or ["16:9", "9:16"])
    opts = {"subtitles": not args.no_subtitles, "c2pa": args.c2pa, "otio": args.otio}
    opts["sound"] = not args.no_sound
    result = export(p, args.episode, aspects=aspects, **opts)
    for path in result["files"]:
        print(f"wrote {path}")
    print(f"{result['clips']} clips, {result['duration']:.2f} s, {result['subtitles']} subtitles")
    return 0


def _previs(p: Project, args: argparse.Namespace) -> int:
    """Write the previs of an episode at $0: no flag gives the sheet and the animatic."""
    from vinci_olf.previs import previs

    both = not (args.sheet or args.animatic or args.mock)  # no flag: the sheet and the animatic
    picks = {"sheet": args.sheet or both, "animatic": args.animatic or both, "mock": args.mock}
    result = previs(p, args.episode, **picks)
    for path in result["files"]:
        print(f"wrote {path}")
    print(f"{result['cuts']} cuts, {result['runtime']:.2f} s, $0 (no model runs)")
    return 0


def _template(p: Project, args: argparse.Namespace) -> int:
    """List the camerawork library (no ID), copy a template into the bible (an ID), or put it
    on a shot (an ID and ``--shot``)."""
    from vinci_olf.api import library
    from vinci_olf.author import add_template, apply_template

    if not args.id:  # the library, with a mark on each template the show has a copy of
        have = {str(doc.data.get("source") or "").partition("@")[0] for doc in p.docs.values()}
        for row in library():
            camera, timing = row.get("camera") or {}, row.get("timing") or {}
            mark = "*" if row["id"] in have else " "
            how = "engine $0" if camera.get("render") == "engine" else "model"
            print(
                f"{mark} {row['id']:<22} {row['family']:<9} {how:<10} "
                f"{timing.get('default', ''):<9} {row['name']}"
            )
        print("* = in this show. `vinci olf template <id> --shot <shot>` puts one on a shot.")
        return 0
    if args.shot:
        done = apply_template(p, args.shot, args.id)
        print(f"{args.shot}: camerawork {done['template']}, duration {done.get('duration', '-')}")
    else:
        print(f"added {add_template(p, args.id)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """Run the CLI. Returns the exit code: 0 ok, 1 invalid project, 2 error."""
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "-C", "--project", default=".", help="project folder (default: the current folder)"
    )
    common.add_argument("-v", "--verbose", action="store_true", help="print logs and tracebacks")
    parser = argparse.ArgumentParser(
        prog="vinci olf", description="Open Lore Format (OLF v0.1) movie engine."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser(
        "validate", parents=[common], help="check schemas, references, assets and the lock file"
    )
    cmd = sub.add_parser(
        "resolve", parents=[common], help="print a shot after the five levels merge"
    )
    cmd.add_argument("shot", help="shot ID, for example e02/s03/sh014")
    cmd.add_argument(
        "--kind", choices=["keyframe", "video", "audio"], help="print what this take kind hashes"
    )
    cmd = sub.add_parser(
        "status", parents=[common], help="list takes with their status and staleness"
    )
    cmd.add_argument("prefix", nargs="?", default="", help="only takes whose ID starts with this")
    cmd = sub.add_parser(
        "render", parents=[common], help="render a shot's keyframe, video or dialogue, or a cue"
    )
    cmd.add_argument("shot", help="shot ID (e02/s03/sh014) or music and SFX cue ID (e02/cue/theme)")
    cmd.add_argument(
        "--kind",
        choices=["keyframe", "video", "audio"],
        default="video",
        help="default: video; audio speaks the shot's dialogue",
    )
    cmd.add_argument("--model", help="model ID for the last step (default: routing preference)")
    cmd.add_argument("--keyframe-model", help="model ID for a new keyframe in a video render")
    cmd.add_argument(
        "--count", type=int, default=1, help="keyframe variations to draw at once (1 to 4)"
    )
    cmd.add_argument("--yes", action="store_true", help="allow a render that costs money")
    cmd.add_argument("--dry-run", action="store_true", help="print the plan and price only")
    cmd = sub.add_parser(
        "batch", parents=[common], help="re-render stale takes or animate approved keyframes"
    )
    cmd.add_argument("episode", help="episode ID, for example e02")
    mode = cmd.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--stale", action="store_true", help="new takes for stale keyframes, videos and dialogue"
    )
    mode.add_argument(
        "--animate-approved",
        action="store_true",
        help="a video for each approved keyframe that has none",
    )
    cmd.add_argument("--yes", action="store_true", help="allow a batch that costs money")
    cmd.add_argument("--dry-run", action="store_true", help="print the jobs and price only")
    cmd = sub.add_parser("review", parents=[common], help="set a take's status and notes")
    cmd.add_argument("take", help="take ID, for example e02/s03/sh014/v1")
    cmd.add_argument("--status", choices=["draft", "candidate", "approved", "rejected"])
    cmd.add_argument("--notes", help="a note; an empty string removes it")
    cmd = sub.add_parser("select", parents=[common], help="pick the takes a shot uses")
    cmd.add_argument("shot", help="shot ID, for example e02/s03/sh014")
    for kind, example in (("keyframe", "kf2"), ("video", "v1"), ("audio", "a1")):
        cmd.add_argument(f"--{kind}", help=f"take name such as {example}, or none to clear")
    cmd = sub.add_parser("cut", parents=[common], help="print an episode's cut as a timeline")
    cmd.add_argument("episode", help="episode ID, for example e02")
    cmd.add_argument(
        "--use-approved", action="store_true", help="first write the cut from approved takes"
    )
    cmd = sub.add_parser("export", parents=[common], help="export the cut as video with subtitles")
    cmd.add_argument("episode", help="episode ID, for example e02")
    cmd.add_argument(
        "--aspect",
        action="append",
        choices=["16:9", "9:16"],
        help="repeat for both (default: both)",
    )
    cmd.add_argument(
        "--no-subtitles", action="store_true", help="no burned-in subtitles and no .srt"
    )
    cmd.add_argument("--c2pa", action="store_true", help="sign each MP4 with a C2PA manifest")
    cmd.add_argument("--otio", action="store_true", help="also write an .otio file and WAV stems")
    cmd.add_argument(
        "--no-sound", action="store_true", help="no audio stream: the lines are only subtitles"
    )
    cmd = sub.add_parser(
        "previs", parents=[common], help="draw the e-conte sheet and the animatic of an episode"
    )
    cmd.add_argument("episode", help="episode ID, for example e02")
    cmd.add_argument("--sheet", action="store_true", help="only the e-conte sheet (PDF and PNG)")
    cmd.add_argument("--animatic", action="store_true", help="only the animatic (MP4)")
    cmd.add_argument(
        "--mock",
        action="store_true",
        help="the mock render (MP4): every shot from its pills, no sound, lines as subtitles",
    )
    cmd = sub.add_parser(
        "template", parents=[common], help="list the camerawork library, or add a template"
    )
    cmd.add_argument("id", nargs="?", help="library ID such as anime/tu-to-eyes (or cam/<slug>)")
    cmd.add_argument("--shot", help="also put the template on this shot")
    args = parser.parse_args(argv)
    level = logging.INFO if args.verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")
    commands = {
        "validate": _validate,
        "resolve": _resolve,
        "status": _status,
        "render": _render,
        "batch": _batch,
        "review": _review,
        "select": _select,
        "cut": _cut,
        "export": _export,
        "previs": _previs,
        "template": _template,
    }
    try:
        return commands[args.cmd](load(args.project), args)
    except Exception as exc:  # noqa: BLE001 - one clear line; -v shows the traceback
        if args.verbose:
            raise
        detail = "" if isinstance(exc, OlfError) else f"{type(exc).__name__}: "
        print(f"error: {detail}{exc} (run with -v for details)", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
