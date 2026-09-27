"""Versioned, backend-aware definitions for the Nebula Blend Creator.

The graph is deliberately a description, not a second compositor.  CreativeCore
remains responsible for rendering; this module validates the editable definition
and exposes the modes/parameters that the active backend actually supports.
"""

from __future__ import annotations

from typing import Any

from DOCUMENTS.blend_modes import BLEND_MODES


GRAPH_FORMAT = "CreativeSystemBlendGraph"
GRAPH_VERSION = 1
NODE_TYPES = (
    "Input", "Analyzer", "Value", "Condition", "Logic", "Curve",
    "Transform", "Blend", "Mask", "Combine", "Output",
)
CHANNELS = ("RGB", "R", "G", "B", "Alpha")


def backend_capabilities() -> dict[str, Any]:
    """Return executable modes from CreativeCore/Nebula, never a local guess."""
    from DOCUMENTS.blend_presets import BLEND_PARAMS

    return {
        "blend_modes": list(BLEND_MODES),
        "parameters": {
            mode: [item["key"] for item in BLEND_PARAMS.get(mode, [])]
            for mode in BLEND_MODES
        },
        "channels": list(CHANNELS),
    }


def default_graph(mode: str = "normal") -> dict[str, Any]:
    if mode not in backend_capabilities()["blend_modes"]:
        mode = "normal"
    return {
        "format": GRAPH_FORMAT,
        "version": GRAPH_VERSION,
        "nodes": [
            {"id": "input", "type": "Input", "source": "layer"},
            {"id": "blend", "type": "Blend", "mode": mode,
             "channel": "RGB", "contribution": {"type": "constant", "value": 1.0}},
            {"id": "output", "type": "Output"},
        ],
        "edges": [
            {"from": "input", "to": "blend"},
            {"from": "blend", "to": "output"},
        ],
        "exposed_parameters": [],
    }


def validate_graph(graph: Any) -> list[str]:
    if not isinstance(graph, dict):
        return ["graph must be an object"]
    if graph.get("format") not in (None, GRAPH_FORMAT):
        return ["unsupported graph format"]
    if graph.get("version", GRAPH_VERSION) != GRAPH_VERSION:
        return ["unsupported graph version"]
    nodes = graph.get("nodes")
    edges = graph.get("edges", [])
    if not isinstance(nodes, list) or not nodes:
        return ["graph must contain nodes"]
    if not isinstance(edges, list):
        return ["graph.edges must be a list"]

    errors: list[str] = []
    ids = [node.get("id") for node in nodes if isinstance(node, dict)]
    if len(ids) != len(set(ids)):
        errors.append("node ids must be unique")
    known = set(ids)
    adjacency = {node_id: [] for node_id in known if node_id}
    capabilities = backend_capabilities()
    for node in nodes:
        if not isinstance(node, dict):
            errors.append("node must be an object")
            continue
        node_type = node.get("type")
        if not node.get("id"):
            errors.append("node id is required")
        if node_type not in NODE_TYPES:
            errors.append(f"unsupported node type: {node_type}")
        if node_type == "Blend":
            mode = node.get("mode")
            if mode not in capabilities["blend_modes"]:
                errors.append(f"unsupported backend blend mode: {mode}")
            if node.get("channel", "RGB") not in CHANNELS:
                errors.append(f"unsupported channel: {node.get('channel')}")
    for edge in edges:
        if not isinstance(edge, dict):
            errors.append("edge must be an object")
            continue
        source, target = edge.get("from"), edge.get("to")
        if source not in known or target not in known:
            errors.append(f"edge references unknown node: {source}->{target}")
        elif source == target:
            errors.append(f"self-cycle: {source}")
        else:
            adjacency[source].append(target)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            errors.append("graph contains a cycle")
            return
        if node_id in visited:
            return
        visiting.add(node_id)
        for child in adjacency.get(node_id, []):
            visit(child)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in known:
        visit(node_id)
    if not any(isinstance(node, dict) and node.get("type") == "Output" for node in nodes):
        errors.append("graph must contain an Output node")
    return sorted(set(errors))
