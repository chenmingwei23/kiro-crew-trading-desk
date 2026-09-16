"""Change values inside a YAML file without touching anything else.

``books.yaml`` and ``sectors.yaml`` carry the desk's reasoning in comments — why a
pod weight was cut, which structure the broker rejected, what a number is for.
Parsing to a dict and dumping it back deletes all of that, and the gateway's
interpreter has no ``ruamel.yaml`` to round-trip with, so the Config page's save
would quietly destroy the file's memory.

So the edit is done on the TEXT. PyYAML's ``compose`` gives every scalar and
sequence node its exact character span in the source, and only those spans are
spliced — every comment, blank line, key order and quoting style outside them
survives byte for byte.

Only value changes are in scope. Adding or removing a key, or changing a value's
shape, raises :class:`Unsupported` so the caller can fall back to a full dump
knowingly rather than corrupt the file.
"""
from __future__ import annotations

from typing import Any, Iterator

import yaml

Path_ = tuple[Any, ...]


class Unsupported(Exception):
    """This change cannot be made as a text splice. Caller should dump instead."""


def _diff(old: Any, new: Any, path: Path_ = ()) -> Iterator[tuple[Path_, Any]]:
    """Yield ``(path, new_value)`` for every changed leaf, or raise Unsupported."""
    where = ".".join(str(p) for p in path) or "<root>"

    if isinstance(old, dict) or isinstance(new, dict):
        if not (isinstance(old, dict) and isinstance(new, dict)):
            raise Unsupported(f"{where}: mapping replaced by a non-mapping")
        added = set(new) - set(old)
        removed = set(old) - set(new)
        if added or removed:
            raise Unsupported(f"{where}: keys added/removed ({sorted(added | removed)})")
        for key in new:
            yield from _diff(old[key], new[key], path + (key,))
        return

    if isinstance(old, list) or isinstance(new, list):
        if not (isinstance(old, list) and isinstance(new, list)):
            raise Unsupported(f"{where}: sequence replaced by a non-sequence")
        if old != new:
            if not all(isinstance(v, (str, int, float, bool)) for v in new):
                raise Unsupported(f"{where}: only sequences of scalars can be spliced")
            yield path, new
        return

    if old != new:
        yield path, new


def _find(root: yaml.Node, path: Path_) -> yaml.Node:
    node = root
    for key in path:
        if not isinstance(node, yaml.MappingNode):
            raise Unsupported(f"{key}: parent is not a mapping in the source")
        for key_node, value_node in node.value:
            if str(getattr(key_node, "value", "")) == str(key):
                node = value_node
                break
        else:
            raise Unsupported(f"{key}: key not found in the source")
    return node


def _scalar_text(value: Any) -> str:
    """Serialize one scalar the way YAML would write it inline."""
    dumped = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True).strip()
    if dumped.endswith("..."):
        dumped = dumped[:-3].strip()
    if "\n" in dumped:
        raise Unsupported("multi-line scalars are not spliced")
    return dumped


def _sequence_text(node: yaml.SequenceNode, values: list[Any], source: str) -> str:
    """Serialize a sequence, matching the block or flow style already in the file."""
    if not values:
        return "[]"
    if getattr(node, "flow_style", False):
        return "[" + ", ".join(_scalar_text(v) for v in values) + "]"
    line_start = source.rfind("\n", 0, node.start_mark.index) + 1
    indent = source[line_start : node.start_mark.index]
    if indent.strip():
        # The sequence starts on the key's own line; indent one level under it.
        indent = " " * (node.start_mark.column)
    joiner = "\n" + indent + "- "
    return "- " + joiner.join(_scalar_text(v) for v in values)


def patch(source: str, old: dict[str, Any], new: dict[str, Any]) -> str:
    """Return ``source`` with ``old``'s values replaced by ``new``'s.

    ``old`` must be what parsing ``source`` produced (JSON-coerced), and ``new``
    the candidate. Raises :class:`Unsupported` for any change that is not a value
    replacement.
    """
    changes = list(_diff(old, new))
    if not changes:
        return source

    root = yaml.compose(source)
    if root is None:
        raise Unsupported("source is empty")

    splices: list[tuple[int, int, str]] = []
    for path, value in changes:
        node = _find(root, path)
        if isinstance(node, yaml.SequenceNode):
            text = _sequence_text(node, list(value), source)
        elif isinstance(node, yaml.ScalarNode):
            text = _scalar_text(value)
        else:
            raise Unsupported(f"{'.'.join(map(str, path))}: unsupported node type")
        splices.append((node.start_mark.index, node.end_mark.index, text))

    out = source
    for start, end, text in sorted(splices, key=lambda s: s[0], reverse=True):
        out = out[:start] + text + out[end:]

    # A splice that broke the document is worse than a dump — prove it still parses.
    try:
        yaml.safe_load(out)
    except yaml.YAMLError as exc:
        raise Unsupported(f"spliced text no longer parses — {exc}") from exc
    return out
