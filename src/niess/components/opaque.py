"""A McStas component niess does not model, carried through verbatim.

Every other class in :mod:`niess.components` is a *statement about an instrument*: a
`DiscChopper` knows its openings, so NeXus can write an `NXdisk_chopper` and CAD can draw
a disc. `Opaque` makes no such statement. It holds a McCode component type name and the
parameters to give it, and it emits exactly that.

It exists for one job: a `.instr` being converted into a niess submodule
(:mod:`niess.scaffold`) contains components niess has no class for -- on a real instrument,
most of them. Without somewhere to put them the converter has two bad options, dropping
them or guessing, and `Component`'s default makes the guess silently: a subclass with no
``__mccode__`` inherits one that emits a bare ``Arm``, so an unmodelled component becomes a
coordinate frame and the simulation quietly changes meaning.

So an `Opaque` is deliberately a placeholder that *says* it is one. Its role is
``unmodelled-component`` rather than ``physical-component``, which is what lets a target
dispatch on "niess does not know what this is" instead of discovering it by finding no
geometry. Counting them in a converted module measures how much of the instrument is still
McStas-shaped, and replacing each one with a real class is the work that makes the module
worth having.

What it is not: a way to avoid writing a component. Emitting McStas is the only thing it
can do. It carries no dimensions, so `niess.brep` has nothing to draw, and `niess.nexus`
has nothing to write beyond a placement. If a component is part of an instrument niess is
meant to model, it needs a class -- three methods, per
"Build a new instrument submodule" in the documentation.
"""
from __future__ import annotations

from typing import Any

from mccode_antlr.assembler import Assembler
from mccode_antlr.instr import Instance

from .component import Component


class Opaque(Component, kw_only=True):
    """A McCode component reproduced as-is, with no niess model behind it.

    Parameters
    ----------
    mccode_type: str
        The McCode component type name, as it appears after ``=`` in a ``COMPONENT`` line.
    mccode_parameters: dict
        What to pass it. Values are emitted as McCode source: numbers as numbers, `str` as
        raw source text (so a file name must carry its own quotes, exactly as it does in a
        ``.instr``), and an `InstrumentParameter` is declared on the instrument and passed
        by name -- which `Component.to_mccode` already does for any component.
    when, group, extend, split, removable:
        The ``WHEN``, ``GROUP``, ``EXTEND``, ``SPLIT`` and ``REMOVABLE`` clauses of the
        original instance, as source text. A converted instrument keeps whatever gating
        and grouping it was written with; niess itself has no use for them.

        Note that ``mccode_antlr`` writes only the first three back out. ``Instance``
        parses and stores ``SPLIT`` and ``REMOVABLE`` -- and they are set here, so
        anything reading the assembled ``Instr`` object sees them -- but
        ``Instance.to_file`` never prints either, so they are lost when that ``Instr`` is
        written as ``.instr`` text. Set faithfully here regardless: the loss is upstream,
        it is being reported there, and this is the side that will be right when it is
        fixed.
    """
    mccode_type: str
    mccode_parameters: dict[str, Any] = {}
    when: str | None = None
    group: str | None = None
    extend: str | None = None
    split: str | None = None
    removable: bool = False

    @classmethod
    def from_calibration(cls, cal: dict):
        return cls(
            name=cal['name'],
            position=cal['position'],
            orientation=cal['orientation'],
            mccode_type=cal['mccode_type'],
            mccode_parameters=dict(cal.get('mccode_parameters', {})),
            when=cal.get('when'),
            group=cal.get('group'),
            extend=cal.get('extend'),
            split=cal.get('split'),
            removable=cal.get('removable', False),
        )

    def __mccode__(self) -> tuple[str, dict]:
        return self.mccode_type, dict(self.mccode_parameters)

    def __mccode_role__(self) -> str:
        """Not ``physical-component``: niess is not claiming to know what this is."""
        return 'unmodelled-component'

    def __mccode_extra__(self) -> dict[str, Any]:
        """Enough to tell, from the emitted file, that this was a placeholder."""
        return {'mccode_type': self.mccode_type}

    def to_mccode(
            self, assembler: Assembler,
            at: Instance | str | None = None, rotate: Instance | str | None = None,
            insert_provenance_metadata: bool = True,
    ):
        """Emit the component, then re-apply the clauses it was written with.

        `Component.to_mccode` places it and writes its parameters; the clauses are ours
        because they came off a specific `Instance` rather than from anything enclosing
        it. The same clauses set by a *composite* arrive through `McCodeContext` instead
        and are applied by `niess.mccode.ComponentTranslator`, so both routes can be in
        play at once and neither overwrites the other.
        """
        instance = super().to_mccode(
            assembler, at=at, rotate=rotate,
            insert_provenance_metadata=insert_provenance_metadata,
        )
        for clause, apply in (
                (self.when, lambda one, v: one.WHEN(v)),
                (self.group, lambda one, v: one.GROUP(v)),
                (self.extend, lambda one, v: one.EXTEND(v)),
                (self.split, lambda one, v: one.SPLIT(v)),
        ):
            if clause is not None:
                apply(instance, clause)
        if self.removable:
            instance.REMOVABLE()
        return instance
