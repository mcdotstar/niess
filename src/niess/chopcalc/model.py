"""What discovery hands to emission.

Every field of a :class:`ChopperEntry` is C *text*, not a number. The array it becomes is
a local in ``init()``, so a field may name a run-time instrument parameter -- which is the
point: change a chopper speed on the command line and the band recomputes without a
rebuild.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChopperEntry:
    """One row of the generated ``chopper_parameters`` array."""

    name: str
    """The instance name, or the disc's group id when several openings share a disc."""
    speed: str
    """Hz. The sign sets the direction of rotation, and is preserved."""
    delay: str
    """Seconds, when the angle ``beam`` is on the beam path."""
    beam: str
    """Degrees from the disc's top-dead-centre mark to where the beam crosses it."""
    edges: tuple[str, ...]
    """The disc's slit edges, in degrees from the mark, two per opening -- the same flat,
    increasing array the ``CollectorDiskChopper`` component and the NeXus
    ``NXdisk_chopper`` standard use. chopper-lib 4.0.0 reads exactly this, so these are
    the disc's own numbers rather than a conversion of them."""
    path: str
    """Metres travelled from the source, along the beam."""
    note: str | None = None
    """Anything worth saying about this row in the generated comment."""


@dataclass(frozen=True)
class SourceEntry:
    """The source, and the two parameters this narrows."""

    name: str
    lambda_min: str
    """An instrument-parameter name. It has to be one: the C writes through its address."""
    lambda_max: str
    latest_emission: str
    """Seconds, as a C expression, so the arithmetic stays visible in the instrument."""
    latest_emission_note: str
    """Where that expression came from, for the generated comment."""


@dataclass(frozen=True)
class Exclusion:
    """A chopper the calculation left out, and why."""

    name: str
    members: tuple[str, ...]
    reason: str


@dataclass(frozen=True)
class Export:
    """Names the chopper train is published under, for components that take it.

    The narrowing's own array is automatic and scoped to its block, which is what keeps
    ``chopcalc_*`` from colliding with anything else in INITIALIZE. A component that takes
    the train as a parameter needs it to outlive that block, so it gets a separate copy at
    file scope: allocated in INITIALIZE, released in FINALLY.
    """

    choppers: str
    """A ``multi_chopper_parameters *`` in DECLARE. Cast it at a component whose own
    parameter is declared ``double *``."""
    count: str
    """An ``int`` in DECLARE, holding how many rows ``choppers`` points at."""


@dataclass(frozen=True)
class ChopperTrain:
    """Everything the calculation found.

    Returned so a build script can assert on what was used without reading generated C.
    """

    source: SourceEntry
    choppers: tuple[ChopperEntry, ...]
    excluded: tuple[Exclusion, ...]
    export: Export | None = None
    """Set when the train was also published for a component to read."""
