"""Walking an instrument, once, for whatever is being built from it.

Every target used to start from an assembled McStas instrument, which meant McStas was
not one output among several but the road to all of them. This is the road they share
instead: a depth-first pass over the niess tree that hands each node to whichever
translator a registry resolves for it.

A visit carries what a translator needs and cannot work out for itself -- where the node
sits in the tree, what the thing it emits should be called, and which frame it is placed
against. What it does *not* carry is anything target-specific: a NeXus class, a McStas
component type and a CAD solid are all decisions for the translator, dispatched on the
niess class rather than on anything the walk knows.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Optional

from .tree import node_id


@dataclass
class Context:
    """Instrument-wide state, shared by every visit.

    Targets subclass this to carry their own -- an ``Assembler``, a dict of emitted
    NeXus nodes -- so the walk itself stays ignorant of what is being built.
    """
    instrument: Any
    registry: Any = None
    nodes: dict = field(default_factory=dict)

    @property
    def origin(self) -> Optional[str]:
        """The component everything else is measured against, if the instrument says."""
        return getattr(self.instrument, 'origin', None)


@dataclass
class Visit:
    """One node of the tree, and everything about where it sits.

    ``path`` identifies the node structurally -- ``tank/channels[2]/pairs[0]/analyzer``
    -- independently of what any target calls it. ``name`` is what a thing emitted here
    is called, built from the labels the ancestors contribute; ``frame`` is what it is
    placed against.
    """
    context: Context
    obj: Any
    path: tuple[str, ...] = ()
    parent: Optional['Visit'] = None
    frame: Optional[str] = None

    @property
    def label(self) -> str:
        """This node's own path label, e.g. ``pairs[0]``."""
        return self.path[-1] if self.path else ''

    @property
    def index(self) -> Optional[int]:
        """This node's position, when it is one of a sequence."""
        from .tree import label_index
        return label_index(self.label)

    @property
    def id(self) -> str:
        """The path as one string, which is what the flow graph is keyed on."""
        return node_id(self.path)

    @property
    def prefix(self) -> str:
        """What the ancestors contribute to a name emitted here.

        Empty for anything under nothing but sections: a guide three sections deep is
        still ``unit_29_straight``. ``channel_3_1`` inside BIFROST's tank.
        """
        parts = []
        node = self.parent
        while node is not None:
            contributed = node.own_label
            if contributed:
                parts.append(contributed)
            node = node.parent
        return '_'.join(reversed(parts))

    @property
    def own_label(self) -> Optional[str]:
        """What this node contributes to names emitted inside it, if anything."""
        contribute = getattr(self.obj, '__niess_label__', None)
        return None if contribute is None else contribute(self.label)

    @property
    def name(self) -> str:
        """What a thing emitted at this node is called.

        A named component keeps its own name, prefixed by whatever contains it. A
        composite has no name of its own, so a translator emitting several components
        here builds them with :meth:`emit_name`.
        """
        own = self.own_label
        if own is None:
            return self.prefix
        return f'{self.prefix}_{own}' if self.prefix else own

    def emit_name(self, suffix: str) -> str:
        """A name for one of several things emitted at this node.

        ``channel_3_1`` plus ``monochromator``. Which suffixes exist is a target's
        business -- ``monochromator`` and ``triplet`` are McStas component names, and
        another target need not have anything to correspond to them.
        """
        stem = self.name
        return f'{stem}_{suffix}' if stem else suffix

    def children(self) -> list['Visit']:
        """The child visits, in declaration order, each carrying the right frame."""
        default = self.frame_for_children()
        return [
            Visit(context=self.context, obj=child, path=self.path + (label,),
                  parent=self, frame=self.frame_of(label, default))
            for label, child in self.obj.__niess_children__()
        ]

    def frame_of(self, label: str, default: Optional[str]) -> Optional[str]:
        """The frame one named child sits in, where they do not all share one.

        An instrument's pieces are the case: BIFROST's primary is described in global
        coordinates and its tank about the sample, so they hang from different things.
        """
        per_child = getattr(self.obj, '__niess_child_frame__', None)
        return default if per_child is None else per_child(self, label, default)

    def frame_for_children(self) -> Optional[str]:
        """The frame this node places its contents in.

        Its own by default. A composite that establishes one -- BIFROST's channel turns
        a cassette about the sample, and everything in it hangs from that -- says so
        with ``__niess_frame__``.
        """
        establish = getattr(self.obj, '__niess_frame__', None)
        return self.frame if establish is None else establish(self)

    def child(self, label: str) -> 'Visit':
        """One named child visit, for a translator that drives its own subtree."""
        for visit in self.children():
            if visit.label == label:
                return visit
        raise KeyError(f'{self.id or "the instrument"} has no child {label!r}')

    def ancestor(self, kind) -> Optional['Visit']:
        """The nearest enclosing visit whose object is an instance of ``kind``.

        What replaces reading an index back out of a generated ``WHEN`` clause: a
        detector's arc and triplet are ``visit.ancestor(Channel).index`` and
        ``visit.ancestor(Arm).index``.
        """
        node = self.parent
        while node is not None:
            if isinstance(node.obj, kind):
                return node
            node = node.parent
        return None


def visits(instrument, context: Optional[Context] = None) -> Iterator[Visit]:
    """Every node of ``instrument``, depth first, in declaration order.

    Declaration order is beam order, so this is the order things are emitted in.
    """
    context = Context(instrument=instrument) if context is None else context
    root = Visit(context=context, obj=instrument)

    def descend(visit: Visit) -> Iterator[Visit]:
        yield visit
        for child in visit.children():
            yield from descend(child)

    yield from descend(root)


def walk(instrument, registry, context: Optional[Context] = None):
    """Drive ``registry``'s translators over ``instrument``.

    A translator may implement ``enter``, ``leaf`` and ``exit``. A node with children
    gets ``enter`` before them and ``exit`` after; one without gets ``leaf``. Returning
    :data:`SKIP` from ``enter`` means the node's children are its own business -- an
    analyzer is seven blades and one component, and the translator that emits it does
    not want the walk descending into them.

    Resolving a translator and calling it are kept apart, as they are everywhere else in
    niess: no translator found is not the same as a translator that ran and declined.
    """
    context = Context(instrument=instrument) if context is None else context
    context.registry = registry
    root = Visit(context=context, obj=instrument)
    drive(root, registry)
    return context


#: Returned from ``enter`` by a translator that consumes its own subtree.
SKIP = object()


def drive(visit: Visit, registry) -> None:
    """Run ``registry`` over one visit and its subtree.

    Public so a composite that emits its own scaffolding between its children can keep
    dispatching them through the registry rather than reaching past it.
    """
    translator = registry.resolve_for_object(visit.obj)
    children = visit.children()

    if not children:
        handler = getattr(translator, 'leaf', None) if translator else None
        if handler is not None:
            handler(visit)
        return

    entered = None
    if translator is not None:
        enter = getattr(translator, 'enter', None)
        if enter is not None:
            entered = enter(visit)
            if entered is SKIP:
                return

    for child in children:
        drive(child, registry)

    if translator is not None:
        leave = getattr(translator, 'exit', None)
        if leave is not None:
            leave(visit, entered)
