"""Import a tiny ComfyUI graph into a Vinci WorkflowSpec.

Maps a text-encode + save-image graph to a single cheapest t2i generate node.
Does not execute ComfyUI. Prompt-only; no custom-node dump.
"""

from __future__ import annotations

from typing import Any

from vinci_protocol.enums import Capability, NodeType
from vinci_protocol.models import WorkflowNode, WorkflowSpec

_PROMPT_TYPES = {
    "CLIPTextEncode",
    "CLIPTextEncodeSDXL",
    "CR Text",
    "Text",
}


def _iter_nodes(graph: dict[str, Any]) -> list[dict[str, Any]]:
    raw = graph.get("nodes")
    if isinstance(raw, list):
        return [n for n in raw if isinstance(n, dict)]
    nodes: list[dict[str, Any]] = []
    for key, node in graph.items():
        if key in {"links", "groups", "config", "extra"} or not isinstance(node, dict):
            continue
        if "class_type" in node or "type" in node:
            row = dict(node)
            row.setdefault("id", key)
            nodes.append(row)
    return nodes


def _prompt_from_node(node: dict[str, Any]) -> str | None:
    ntype = str(node.get("type") or node.get("class_type") or "")
    if ntype not in _PROMPT_TYPES:
        return None
    widgets = node.get("widgets_values")
    if isinstance(widgets, list) and widgets:
        text = widgets[0]
        if isinstance(text, str) and text.strip():
            return text
    inputs = node.get("inputs")
    if isinstance(inputs, dict):
        text = inputs.get("text") or inputs.get("prompt")
        if isinstance(text, str) and text.strip():
            return text
    return None


def import_comfy(graph: dict[str, Any], *, workflow_id: str = "@imported/comfy") -> WorkflowSpec:
    if not isinstance(graph, dict):
        raise ValueError("ComfyUI graph must be an object")
    prompt = ""
    for node in _iter_nodes(graph):
        found = _prompt_from_node(node)
        if found:
            prompt = found
            break
    if not prompt:
        prompt = "{{inputs.prompt}}"
    return WorkflowSpec(
        id=workflow_id,
        version="0.1.0",
        nodes=[
            WorkflowNode(
                id="generate",
                type=NodeType.GENERATE,
                capability=Capability.T2I,
                params={"prompt": prompt},
            )
        ],
        edges=[],
    )
