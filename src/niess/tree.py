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


# -- particle flow -------------------------------------------------------------
#
# McCode describes an instrument as a list, so the only flow it can express is the order
# the components are declared in. That is enough for a guide, and not enough for the
# BIFROST tank, where ten paths leave the sample -- nine channels and the elastic
# monitor -- and a neutron takes one of them. NeXus can say so, through each group's
# `inputs` and `outputs`, so niess has to know it.
#
# A composite therefore declares how flow passes through it, and gets the same default
# every other structure question gets: children in declaration order. Only the ones that
# branch, or that are one thing however many parts they have, need to say otherwise.
#
# Nodes are tree paths rather than the objects themselves: Base defines __eq__ without
# __hash__, so its instances cannot be graph keys, and a path identifies a node without
# borrowing any one target's names for it.


def label_index(label: str) -> int | None:
    """The index in a sequence label: ``pairs[3]`` is 3, ``analyzer`` is nothing."""
    if label.endswith(']') and '[' in label:
        try:
            return int(label[label.rindex('[') + 1:-1])
        except ValueError:
            return None
    return None


def node_id(path: tuple[str, ...]) -> str:
    """A tree path as one string, which is what the graph is keyed on."""
    return '/'.join(path) if path else ''


def chain_flow(node, graph, path):
    """Children in declaration order, each feeding the next.

    The default, and what a section, a segmented guide, a channel or an arm wants.
    Returns the paths flow enters this node by and the paths it leaves by.
    """
    children = node.__niess_children__()
    if not children:
        graph.add_node(node_id(path), kind=type(node).__name__)
        return (node_id(path),), (node_id(path),)

    entries: tuple[str, ...] = ()
    exits: tuple[str, ...] = ()
    for label, child in children:
        child_entries, child_exits = child.__niess_flow__(graph, path + (label,))
        if not child_entries and not child_exits:
            # transparent: a coordinate frame is not a thing a neutron passes through,
            # so the components either side of it chain as though it were not there
            continue
        if not entries:
            entries = child_entries
        for source in exits:
            for target in child_entries:
                graph.add_edge(source, target)
        exits = child_exits
    return entries, exits


def leaf_flow(node, graph, path):
    """One node, however many parts it has.

    An analyzer is seven blades and a triplet is three tubes, but a neutron meets each
    as a single thing -- one component in McStas, one group in NeXus. They keep their
    children, which is what lets a translator reach the real blade positions; they just
    do not have flow running through them.
    """
    graph.add_node(node_id(path), kind=type(node).__name__)
    return (node_id(path),), (node_id(path),)


def flow_graph(root):
    """The particle flow through ``root``, as a networkx DiGraph over tree paths."""
    from networkx import DiGraph

    graph = DiGraph()
    root.__niess_flow__(graph, ())
    return graph
