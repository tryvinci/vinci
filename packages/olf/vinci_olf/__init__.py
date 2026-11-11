"""Open Lore Format (OLF) v0.1: the Vinci movie engine.

Reader: ``load`` a project, ``validate`` it, ``resolve`` a shot, compare ``inputs_hash``
with each take (``stale``). Renderer: ``vinci_olf.render.render`` and, for an episode,
``vinci_olf.batch.render_batch`` (both need the Vinci runtime).
The spec is ``SPEC.md`` next to this package.
"""

from vinci_olf.project import SPEC, OlfError, Project, load
from vinci_olf.resolve import canonical, hash_view, inputs_hash, merge, resolve, stale
from vinci_olf.validate import Issue, validate

__all__ = [
    "SPEC",
    "Issue",
    "OlfError",
    "Project",
    "canonical",
    "hash_view",
    "inputs_hash",
    "load",
    "merge",
    "resolve",
    "stale",
    "validate",
]
