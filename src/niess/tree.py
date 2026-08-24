"""How a niess object says what it contains.

An instrument is a tree -- sections holding components, a tank holding channels holding
arms -- but until now that tree was only ever walked by code that already knew its
shape: ``Section.to_mccode_flat`` looped over declared fields, the composites in
``niess.bifrost`` hand-rolled their own traversal, and each one wrote it out again for
``add_to_graph``. Every consumer re-derived the same structure.

This is that structure, declared once. ``__niess_children__`` gives a node's children in
declaration order, and declaration order is beam order -- ``niess.teaching.primary`` says
so, and ``Tank``'s fields were put in emission order to keep it true.

The default reads the msgspec fields and needs no per-class adoption: every composite in
the codebase is described correctly by it except ``EllipticGuide``, whose two
``PartialEllipse`` fields describe a cross-section rather than naming child components.
If a class needs an override, prefer fixing the default -- one class out of ten wanting
something else is a special case, two would be a wrong rule.

Node-ness is duck-typed rather than an isinstance check, because the two roots do not
share a base: ``Base`` is what components and composites derive from, ``Section`` is a
separate ``msgspec.Struct``, and neither inherits the other.
"""
from __future__ import annotations

from msgspec.structs import fields


def is_node(value) -> bool:
    """Whether a value is a niess tree node rather than data."""
    return hasattr(value, '__niess_children__')


def component_fields(node):
    """The declared fields of ``node`` that are not per-class extras.

    Underscore-prefixed names are extras -- ``Section._flat`` controls how a section
    inserts itself into an assembler, and a subclass may add others. None of them is a
    component, so none is a child.
    """
    return [f for f in fields(node) if not f.name.startswith('_')]


def default_children(node) -> tuple[tuple[str, object], ...]:
    """``(label, child)`` pairs from ``node``'s fields, in declaration order.

    A field holding a node is one child under the field's own name. A field holding a
    sequence of them is one child per element, labelled ``field[i]``. Everything else is
    data: ``Triplet.resistances`` is a scipp Variable, ``SegmentedGuide.name`` a string,
    and neither is a thing in the beam.

    The test is on the *value*, not the annotation, because the annotations do not carry
    it -- ``SegmentedGuide.segments`` is declared as a bare ``list``.
    """
    found: list[tuple[str, object]] = []
    for field in component_fields(node):
        value = getattr(node, field.name)
        if is_node(value):
            found.append((field.name, value))
        elif isinstance(value, (list, tuple)) and len(value):
            nodes = [is_node(item) for item in value]
            if all(nodes):
                found.extend((f'{field.name}[{i}]', v) for i, v in enumerate(value))
            elif any(nodes):
                raise TypeError(
                    f'{type(node).__name__}.{field.name} mixes components with data; '
                    f'a field is either all children or none, or half a composite goes '
                    f'silently missing from every walk'
                )
    return tuple(found)


def walk(node, label: str = ''):
    """Depth-first ``(path, node)`` pairs, this node first, in declaration order.

    ``path`` is the tuple of labels from the root, which is what gives a node an
    identity independent of any one target's naming.
    """
    path = (label,) if label else ()
    yield path, node
    for child_label, child in node.__niess_children__():
        for child_path, descendant in walk(child, child_label):
            yield path + child_path, descendant


def leaves(node):
    """Every node with no children of its own."""
    return [(path, found) for path, found in walk(node)
            if not found.__niess_children__()]
