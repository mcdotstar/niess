"""McStas, as one translation target among several.

Emission used to be the trunk: `to_mccode` walked the tree itself, and everything else --
NeXus, tof, CAD -- read what it produced. Here it reads the same walk every other target
reads, and what makes that believable is that the instrument it emits is unchanged, byte
for byte, against the goldens in `tests/data/baseline`.

There is nothing about any particular component in this module. What a class contributes
to a McStas instrument is written on the class, next to the fields it is contributing it
from; this is only the machinery that drives it. See `ObjectTranslator` for the hooks.

What the walk supplies, so no translator works it out for itself:

  names   `channel_3_radial_filter_collimator` is the filter's own name under what the
          channel contributes, not an f-string rebuilt at emission time
  frames  what a component is placed against, threaded down from the mounting
  order   declaration order, which is beam order
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..dispatch import NiessRegistry
from ..walk import Context, Visit, walk


@dataclass
class McCodeContext(Context):
    """The assembler being built into, and the section scopes open around it."""
    assembler: Any = None
    scopes: list = field(default_factory=list)
    #: Per-visit frame overrides, keyed by visit id. A composite that emits a coordinate
    #: frame of its own puts its contents in it this way. Once frames are declared nodes
    #: in the tree rather than emission artefacts, this goes away.
    frames: dict = field(default_factory=dict)
    #: Per-visit WHEN clauses, same idea: which channel a neutron was tagged with is
    #: per-particle state, so it is McStas's business and not the tree's.
    whens: dict = field(default_factory=dict)

    def push(self, opened) -> Any:
        """Open a nested `%include` and emit into it until it is closed."""
        child = opened.__enter__()
        self.scopes.append((opened, self.assembler))
        self.assembler = child
        return opened

    def pop(self) -> None:
        opened, parent = self.scopes.pop()
        self.assembler = parent
        opened.__exit__(None, None, None)


class ObjectTranslator:
    """Dispatches to the hooks a niess class defines for itself.

    Everything a class contributes to a McStas instrument is written on the class:

    ``__mccode__``
        what the thing *is* -- one COMPONENT line and its parameters.
    ``to_mccode``
        override to contribute something to the instrument around it -- a run-time knob,
        a value computed at start-up, a lookup table. Do the work, then delegate.
    ``__mccode_enter__``
        what a composite needs around its contents: a coordinate frame to hang them
        from, a user variable they share, an ``%include`` to put them in.
    ``__mccode_exit__``
        closing whatever that opened.

    A registered translator still wins. That is what an instrument-specific conversion
    needs, and a class you do not own -- the same reason `niess.nexus` keeps BIFROST's
    translators off the shared registry rather than letting an import change another
    instrument's output. But nothing has to be registered for the ordinary case: write
    the method on the class and it is found.
    """

    def __init__(self, obj):
        self.obj = obj

    @staticmethod
    def handles(obj) -> bool:
        return any(hasattr(obj, hook)
                   for hook in ('__mccode_enter__', '__mccode_exit__'))

    def enter(self, visit: Visit):
        hook = getattr(self.obj, '__mccode_enter__', None)
        return None if hook is None else hook(visit)

    def exit(self, visit: Visit, entered) -> None:
        hook = getattr(self.obj, '__mccode_exit__', None)
        if hook is not None:
            hook(visit, entered)


class NiessMcCodeRegistry(NiessRegistry):
    """Translator lookup for the McStas target.

    Falls back to the object's own ``__mccode_*__`` hooks, so a class that describes its
    own conversion needs no registration at all.
    """

    def resolve_for_object(self, obj):
        registered = super().resolve_for_object(obj)
        if registered is not None:
            return registered
        return ObjectTranslator(obj) if ObjectTranslator.handles(obj) else None


MCCODE_REGISTRY = NiessMcCodeRegistry()


@MCCODE_REGISTRY.register('niess.components.component.Component')
class ComponentTranslator:
    """One component, placed in the frame the walk handed it.

    The emission is the component's own ``__mccode__``/``to_mccode``. What the walk adds
    is the name it is emitted under and the frame it sits in -- a component whose emitted
    name differs from its calibrated one is emitted as a renamed copy, so emission reads
    the tree without writing to it.
    """

    @staticmethod
    def leaf(visit: Visit):
        from msgspec.structs import replace
        context = visit.context
        obj = visit.obj
        if visit.name != obj.name:
            obj = replace(obj, name=visit.name)
        frame = context.frames.get(visit.id, visit.frame)
        instance = obj.to_mccode(context.assembler, at=frame, rotate=frame)
        when = context.whens.get(visit.id)
        if when is not None:
            instance.WHEN(when)
        return instance


def to_mccode(instrument, registry=None, assembler=None):
    """Emit ``instrument`` as a McStas instrument.

    Pass an ``assembler`` to build into an existing one; otherwise one is made from the
    instrument's own name and flavour.
    """
    from mccode_antlr.assembler import Assembler

    if assembler is None:
        assembler = Assembler(instrument.name, flavor=instrument.flavor)
    context = McCodeContext(instrument=instrument, assembler=assembler)
    walk(instrument, MCCODE_REGISTRY if registry is None else registry, context=context)
    if context.scopes:
        raise RuntimeError(
            f'{len(context.scopes)} section scope(s) left open; a translator opened one '
            f'without closing it'
        )
    return assembler.instrument
