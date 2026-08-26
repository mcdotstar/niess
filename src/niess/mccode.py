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

This module is the McStas *target*, so it sits above `niess.dispatch` alongside
`niess.nexus`, `niess.brep` and `niess.tof`. The low-level helpers a component uses to
write itself into an Assembler are a different layer and live below dispatch, in
`niess.assembler` and `niess.provenance`; they used to share this module's name, which
made the McStas target impossible to import from its own subject package.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .dispatch import NiessRegistry
from .walk import Context, Visit, walk


@dataclass
class McCodeContext(Context):
    """The assembler being built into, and the section scopes open around it."""
    assembler: Any = None
    scopes: list = field(default_factory=list)
    #: Per-visit WHEN clauses, same idea: which channel a neutron was tagged with is
    #: per-particle state, so it is McStas's business and not the tree's.
    whens: dict = field(default_factory=dict)
    #: The name emitted at each visit, so a frame can be named as the thing another
    #: component is placed relative to. Names rather than instances because that is what
    #: a placement refers to, and what an Assembler resolves.
    emitted: dict = field(default_factory=dict)

    def push(self, opened) -> Any:
        """Open a nested `%include` and emit into it until it is closed."""
        child = opened.__enter__()
        self.scopes.append((opened, self.assembler))
        self.assembler = child
        return opened

    def reference(self, frame):
        """What a frame reference names in the instrument being built.

        The walk hands down a *tree path* -- ``tank/channels[0]/cassette`` -- because a
        path identifies a frame without borrowing any one target's names for it. This is
        where it becomes the thing McStas places against. A reference that is not a path
        is a component name, which is what a Mount's ``relative_to`` gives.
        """
        return self.emitted.get(frame, frame)

    def pop(self) -> None:
        opened, parent = self.scopes.pop()
        self.assembler = parent
        opened.__exit__(None, None, None)


class NiessMcCodeRegistry(NiessRegistry):
    """Translator lookup for the McStas target.

    Created with ``hooks='mccode'``, so a class carrying ``__mccode_enter__``,
    ``__mccode_leaf__`` or ``__mccode_exit__`` is its own translator and needs no
    registration. See :class:`niess.dispatch.ClassHooks`.
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent, hooks='mccode')


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
        frame = context.reference(visit.frame)
        instance = obj.to_mccode(context.assembler, at=frame, rotate=frame)
        # a component may emit more than one: a disc chopper whose openings are neither
        # identical nor evenly spaced becomes one grouped component per opening
        emitted = instance if isinstance(instance, (list, tuple)) else [instance]
        when = context.whens.get(visit.id)
        if when is not None:
            for one in emitted:
                one.WHEN(when)
        # the first is what anything placed against this node refers to
        context.emitted[visit.id] = emitted[0].name
        return instance


def to_mccode(instrument, registry=None, assembler=None):
    """Emit ``instrument`` as a McStas instrument.

    Pass an ``assembler`` to build into an existing one; otherwise one is made from the
    instrument's own name and flavour.
    """
    from mccode_antlr.assembler import Assembler

    from .assembler import ensure_runtime_parameter

    if assembler is None:
        assembler = Assembler(instrument.name, flavor=instrument.flavor)
    # What the instrument declares of its own accord, before anything it contains gets
    # to declare its own. `Instrument.parameters` exists so a knob can be stated up
    # front rather than created as a side effect by whichever component happens to want
    # one, and an instrument that states one and does not emit it has not declared
    # anything at all.
    for parameter in instrument.parameters:
        ensure_runtime_parameter(assembler, parameter)
    context = McCodeContext(instrument=instrument, assembler=assembler)
    walk(instrument, MCCODE_REGISTRY if registry is None else registry, context=context)
    if context.scopes:
        raise RuntimeError(
            f'{len(context.scopes)} section scope(s) left open; a translator opened one '
            f'without closing it'
        )
    return assembler.instrument
