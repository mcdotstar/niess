"""McStas, as one translation target among several.

Emission used to be the trunk: `to_mccode` walked the tree itself, and everything else
-- NeXus, tof, CAD -- read what it produced. Here it reads the same walk every other
target reads, and what makes that believable is that the instrument it emits is
unchanged, byte for byte, against the goldens in `tests/data/baseline`.

What the walk supplies, and this no longer works out for itself:

  names       `channel_3_radial_filter_collimator` is the filter's own name under what
              the channel contributes, not an f-string rebuilt at emission time.
  frames      what a component is placed against, threaded down from the mounting.
  order       declaration order, which is beam order.

What stays here is everything McStas-shaped: the coordinate-frame `Arm`s that exist so
other components can be placed relative to them, the `%include` sections, the `WHEN` and
`EXTEND` clauses that carry per-particle state, and the generated C.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..dispatch import NiessRegistry
from ..walk import Context, Visit, walk


@dataclass
class McCodeContext(Context):
    """The assembler being built into, and the section scopes open around it."""
    assembler: Any = None
    scopes: list = field(default_factory=list)

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


class NiessMcCodeRegistry(NiessRegistry):
    """Translator lookup for the McStas target, keyed on the niess class."""


MCCODE_REGISTRY = NiessMcCodeRegistry()


def _section_scope_name(visit: Visit) -> str:
    """What a nested section's sub-instrument is called.

    `Guides` inside `teaching` becomes `teaching_guides`, which is the name the emitted
    `%include` carries.
    """
    import re
    spaced = re.sub('([A-Z]+)', r'_\1', type(visit.obj).__name__).lower()
    return f'{visit.context.assembler.name}{spaced}'


@MCCODE_REGISTRY.register('niess.components.section.Section')
class SectionTranslator:
    """A section is a scope, not a component.

    Without `_flat` it becomes an `%include`d sub-instrument, so the emitted McStas
    mirrors how the beamline is thought about rather than being one flat list.
    """

    @staticmethod
    def enter(visit: Visit):
        if getattr(visit.obj, '_flat', False):
            return None
        return visit.context.push(
            visit.context.assembler.included(_section_scope_name(visit))
        )

    @staticmethod
    def exit(visit: Visit, entered) -> None:
        if entered is not None:
            visit.context.pop()


@MCCODE_REGISTRY.register('niess.components.component.Component')
class ComponentTranslator:
    """One component, placed in the frame the walk handed it.

    The emission itself is still the component's own `__mccode__`/`to_mccode`, which is
    where the knowledge of McStas component types and their parameters belongs. What
    changed is that the name and the frame come from the walk: a component whose emitted
    name differs from the one it was calibrated with is emitted as a renamed copy, so
    the tree it came from is left as it was.
    """

    @staticmethod
    def leaf(visit: Visit):
        from msgspec.structs import replace
        obj = visit.obj
        if visit.name != obj.name:
            obj = replace(obj, name=visit.name)
        return obj.to_mccode(visit.context.assembler, at=visit.frame,
                             rotate=visit.frame)


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
