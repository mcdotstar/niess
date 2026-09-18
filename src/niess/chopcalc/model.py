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
    """Seconds, when the disc's zero-angle point is on the path."""
    beam: str
    """The beam angle, in degrees."""
    edge_count: int
    """The number of edges, in case they are already inserted as a stack array."""
    edges: tuple[str, ...] | str
    """The ordered even-length list of opening edges, starting with an opening edge
    and spanning no more than 360.0 degrees, measured relative from the zero-angle point.
    chopper-lib puts any angle `edge` on the zero-angle point at
        ``delay + edge / (360 * speed)``
    so these are signed ant the sign of ``speed`` decided with edge of a pair is reached
    first. The provided input may be a single string, in which case it is expected
    to be the identifier name of a stack array already inserted in DECLARE."""
    path: str
    """Metres travelled from the source, along the beam."""
    aperture: str
    """The *angular* size of the chopper opening, used in setting the inverse-velocity
    emission-time mask"""
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
    values: tuple[int, ...]
    """The indexes of the allocated edge arrays"""


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
