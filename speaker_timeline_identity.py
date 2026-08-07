#!/usr/bin/env python3
"""Contradiction-safe cross-window speaker identity linking."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, Mapping

from speaker_timeline_types import SpeakerLink, _require_probability


@dataclass
class _SpeakerComponent:
    """Mutable union-find metadata for one candidate global speaker."""

    parent: tuple[str, str]
    rank: int
    chunk_labels: dict[str, str]


class _SpeakerUnionFind:
    """Union-find that forbids two local labels from one chunk in a component."""

    def __init__(self, nodes: Iterable[tuple[str, str]]) -> None:
        """Initialize one independent component per speaker node."""
        self._components: dict[tuple[str, str], _SpeakerComponent] = {
            node: _SpeakerComponent(parent=node, rank=0, chunk_labels={node[0]: node[1]})
            for node in nodes
        }

    def find(self, node: tuple[str, str]) -> tuple[str, str]:
        """Return the canonical root with path compression."""
        component = self._components[node]
        if component.parent != node:
            component.parent = self.find(component.parent)
        return component.parent

    def union(self, left: tuple[str, str], right: tuple[str, str]) -> bool:
        """Merge components when their same-chunk labels do not conflict."""
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return True
        left_component = self._components[left_root]
        right_component = self._components[right_root]
        for chunk_id, speaker in right_component.chunk_labels.items():
            existing = left_component.chunk_labels.get(chunk_id)
            if existing is not None and existing != speaker:
                return False
        if left_component.rank < right_component.rank:
            left_root, right_root = right_root, left_root
            left_component, right_component = right_component, left_component
        right_component.parent = left_root
        left_component.chunk_labels.update(right_component.chunk_labels)
        if left_component.rank == right_component.rank:
            left_component.rank += 1
        return True


def _validate_link(link: SpeakerLink, nodes: set[tuple[str, str]]) -> None:
    """Validate one link against known chunk-local speaker nodes."""
    if not isinstance(link, SpeakerLink):
        raise ValueError("links must contain SpeakerLink values")
    _require_probability(link.similarity, "link similarity")
    left = (link.source_chunk_id, link.source_speaker)
    right = (link.target_chunk_id, link.target_speaker)
    if left == right:
        raise ValueError("speaker links must connect distinct nodes")
    if left not in nodes or right not in nodes:
        raise ValueError(f"unknown speaker node in link: {left!r} -> {right!r}")


def _canonical_link_nodes(link: SpeakerLink) -> tuple[tuple[str, str], tuple[str, str]]:
    """Return link endpoints in stable lexical order."""
    left = (link.source_chunk_id, link.source_speaker)
    right = (link.target_chunk_id, link.target_speaker)
    return tuple(sorted((left, right)))  # type: ignore[return-value]


def _build_global_speaker_map(
    nodes: set[tuple[str, str]],
    union_find: _SpeakerUnionFind,
    first_seen: Mapping[tuple[str, str], float],
) -> dict[str, str]:
    """Assign stable global labels by earliest appearance then lexical node."""
    members_by_root: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for node in sorted(nodes):
        members_by_root.setdefault(union_find.find(node), []).append(node)
    ordered_roots = sorted(
        members_by_root,
        key=lambda root: (
            min(first_seen.get(node, math.inf) for node in members_by_root[root]),
            min(members_by_root[root]),
        ),
    )
    label_by_root = {root: f"SPEAKER_{index:02d}" for index, root in enumerate(ordered_roots, start=1)}
    return {
        f"{chunk_id}:{speaker}": label_by_root[union_find.find((chunk_id, speaker))]
        for chunk_id, speaker in sorted(nodes)
    }
