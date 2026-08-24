"""The whole instrument, as one object.

Until now there was no such thing. An instrument existed only as a sequence of calls --

    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    Primary.from_calibration(primary_parameters()).to_mccode(assembler)
    Tank.from_calibration(tank_parameters()).to_mccode(assembler, 'sample_origin')

-- so "the whole of BIFROST" was something that happened inside an ``Assembler`` and
nowhere else. Anything wanting to walk an instrument had to be handed the pieces and
told how they fit together, which is why every target's entry point takes an assembled
McStas instrument rather than a niess object.

An ``Instrument`` says it once. It is a tree node like any other, so it walks, it has a
flow graph, and the pieces keep their own identities inside it.
"""
from __future__ import annotations

from typing import Any, Optional

import msgspec
from mccode_antlr import Flavor
from mccode_antlr.common import InstrumentParameter

from .components.component import Base


class Mount(msgspec.Struct):
    """A top-level piece of an instrument, and the frame it hangs from.

    ``relative_to`` names a component emitted by an earlier piece. BIFROST's tank is
    described in coordinates about the sample -- its first analyzer sits at
    ``[1.189, 0, 0]``, not 162 m down the guide -- so it hangs from ``sample_origin``,
    which the primary provides. A piece whose coordinates are already global, as the
    primary's are, hangs from nothing.

    The name is the path label its contents appear under, so a blade deep inside BIFROST
    is ``tank/channels[2]/pairs[0]/analyzer/blades[3]`` rather than starting at
    ``channels[2]``.
    """
    name: str
    content: Any
    relative_to: Optional[str] = None


class Instrument(Base):
    """An instrument: what it is called, what it is made of, and what it is for.

    ``origin`` names the component other things are measured against -- the sample
    position. Targets need it and each currently guesses: ``niess.nexus`` looks for a
    component of McStas category ``samples`` and warns when it cannot find one, and
    callers pass ``origin='sample_origin'`` by hand. It is a property of the instrument,
    so it is recorded here.

    ``parameters`` are the knobs a run can turn. They are created during emission today,
    by whichever component happens to want one; holding them here lets an instrument
    declare them up front instead.
    """
    name: str
    parts: tuple[Mount, ...]
    flavor: Flavor = Flavor.MCSTAS
    origin: Optional[str] = None
    parameters: tuple[InstrumentParameter, ...] = ()

    @classmethod
    def of(cls, name: str, **parts):
        """Build from keyword pieces, in the order given.

        ``Instrument.of('bifrost', primary=..., tank=...)`` -- for the common case where
        every piece is either global or hangs from the instrument's own origin. Pass a
        ``Mount`` for anything that needs to say what it hangs from.
        """
        mounted = tuple(
            part if isinstance(part, Mount) else Mount(name=label, content=part)
            for label, part in parts.items()
        )
        return cls(name=name, parts=mounted)

    def __niess_children__(self):
        """The pieces, under their own labels -- the Mount itself is not a node."""
        return tuple((mount.name, mount.content) for mount in self.parts)

    def __niess_child_frame__(self, label: str, default):
        """Each piece hangs where its Mount says, not where the one before it did."""
        return self.mount_of(label).relative_to or default

    def mount_of(self, label: str) -> Mount:
        """The Mount a top-level piece arrived in."""
        for mount in self.parts:
            if mount.name == label:
                return mount
        raise KeyError(f'{self.name} has no part called {label!r}')
