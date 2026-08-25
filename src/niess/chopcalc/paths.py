"""How far along the beam a thing is, and the errors that says it cannot be told.

Route-neutral: reading the tree and reading an emitted instrument disagree about how to
find out *where* something is, but not about what to do with two positions once they are
known. Both routes measure along the particle flow graph rather than straight, so a
curved guide is followed rather than chorded.

`niess.tof` measures the same distances for its detectors, which is why this is its own
module rather than a private corner of either route.
"""
from __future__ import annotations

import logging
from math import acos, degrees, dist

logger = logging.getLogger(__name__)

ESS_SOURCE_DURATION = 2.857e-3  # seconds; matches niess.components.source

DEFAULT_LATEST_EMISSION = 3 * ESS_SOURCE_DURATION

OFF_BEAM_TURN = 1.0  # degrees the beam may bend on arrival before it looks like a detour

class ChopcalcError(RuntimeError):
    """The band could not be worked out, and the reason is worth acting on."""

def _c_double(value: float) -> str:
    """A float that still looks like a double once printed."""
    text = f'{float(value):.12g}'
    return text if any(c in text for c in '.e') else text + '.0'

def beam_path_length(graph, places, source: str, chopper: str) -> float:
    """How far a neutron travels from the source to the chopper, in metres.

    Walked along the particle flow graph rather than measured straight, so a curved guide
    is followed instead of chorded. A chopper's emitted position is already the point
    where the beam crosses its disc -- that is what niess' ``offset`` converts to -- so
    the endpoints need no correction.
    """
    from networkx import shortest_path

    route = shortest_path(graph, source, chopper)
    missing = [n for n in route if n not in places]
    if missing:
        raise ChopcalcError(
            f'the beam path from {source!r} to {chopper!r} passes {missing[0]!r}, whose '
            f'position depends on a run-time parameter and cannot be measured'
        )
    walked = sum(dist(places[u], places[v]) for u, v in zip(route, route[1:]))

    turn = _arrival_turn(places, route)
    if turn is not None and turn > OFF_BEAM_TURN:
        logger.warning(
            'niess.chopcalc: the beam turns %.2f degrees to arrive at %r, so its flight '
            'path of %.4f m probably includes a detour. A DiskChopper AT must be where '
            'the beam crosses the disc, not at the spindle -- check that the '
            'calibration subtracts its offset. Pass path_lengths={%r: ...} to override.',
            turn, chopper, walked, chopper,
        )
    return walked

def _arrival_turn(places, route) -> float | None:
    """How sharply the beam turns at the last step, in degrees.

    A component that is not on the beam is reached by a detour, and a detour bends the
    path. Guide curvature does not: it is spread along the guide segments, so every
    BIFROST chopper measures 0.0000 degrees here while a disc placed at its spindle
    rather than at the beam measures several.
    """
    # The last three *distinct* places, not the last three nodes: components sharing a
    # position -- the openings of one multi-slit disc, or a reference frame sitting on
    # the thing it places -- contribute segments of no length and no direction, and
    # taking those as the arrival would silence the check rather than answer it.
    distinct = []
    for name in reversed(route):
        place = places[name]
        if not distinct or dist(place, distinct[-1]) > 0:
            distinct.append(place)
        if len(distinct) == 3:
            break
    if len(distinct) < 3:
        return None
    after, at, before = distinct
    first = [b - a for a, b in zip(before, at)]
    second = [b - a for a, b in zip(at, after)]
    lengths = dist((0, 0, 0), first) * dist((0, 0, 0), second)
    if lengths == 0:
        return None
    cosine = sum(x * y for x, y in zip(first, second)) / lengths
    return degrees(acos(max(-1.0, min(1.0, cosine))))


def global_position(visit):
    """Where a node is, as three numbers, in the frame the calculation works in.

    Only nodes placed absolutely have one. Everything the band depends on -- the source
    and the discs before the sample -- is placed that way; a chopper mounted in a turned
    frame would need the frames composing first, and this says so rather than quietly
    measuring from the wrong origin.
    """
    if visit.frame is not None:
        raise ChopcalcError(
            f'{visit.name!r} is placed in the frame {visit.frame!r}, and the beam path '
            f'is measured in the instrument frame. Composing frames is not implemented, '
            f'because nothing before the sample needs it.'
        )
    # A disc chopper's `position` is its spindle; the beam crosses the disc somewhere
    # else entirely, and `__mccode_offset__` is what converts between them. The path
    # length wants the crossing, so the same correction the emission makes is made here.
    obj = visit.obj
    offset = getattr(obj, '__mccode_offset__', None)
    place = obj.position if offset is None else obj.position + offset()
    return tuple(float(v) for v in place.to(unit='m').value)
