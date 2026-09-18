"""Turn a `.instr`'s `AT`/`ROTATED` chain into niess positions and orientations.

The rule this module exists to enforce: **transcribe, do not re-chain.** Every component
keeps the reference it was given and the local offset it was given, so the absolute
placements come out identical to the original by construction rather than by care.

`docs/how-to/translate-an-instr.md` warns at length about carrying a component's own
offset into everything downstream -- a disc chopper whose centre sits below the beam is
its example. That hazard belongs to a *human* re-chaining an instrument by hand, deciding
afresh what each component hangs off. A literal transcription cannot hit it: if the
original said `AT (0, -0.35, 3.25) RELATIVE unit_2`, so does this, and the next component
still hangs off `unit_2`.

It returns as a real hazard exactly once, in `niess.scaffold.recipes`, where a niess class
measures from a different point than the McStas component it emits. `DiscChopper` is the
case: its `position` is the spindle and its emitted `AT` is the beam crossing. That is the
recipe's problem to invert, and `niess.scaffold.verify` is what catches it getting it
wrong.
"""
from __future__ import annotations

from typing import Any, NamedTuple

from scipp import Variable, vector

from ..spatial import at_relative, mccode_quaternion


class Placement(NamedTuple):
    """Where one component ended up, and what it was measured from."""
    position: Variable
    orientation: Variable
    #: The instance the original `AT` hung off, or `None` for `ABSOLUTE`.
    at_reference: str | None
    #: The instance the original `ROTATED` hung off, which need not be the same one.
    rotate_reference: str | None
    #: The `AT` offset as written, in metres, before the reference was applied.
    local_position: Variable
    #: The `ROTATED` angles as written, in degrees.
    local_angles: tuple[float, float, float]
    #: The `AT` offset as it was *written* -- `Expr` per axis, kept symbolic. The numbers
    #: above are the calibration; these are the structure the author expressed, and
    #: `niess.scaffold.emit` writes them back out wherever it can so a generated module
    #: reads like `GUI_start * m * z` rather than `2.0 * m * z`.
    local_position_source: tuple[Any, Any, Any] = (None, None, None)
    #: The `ROTATED` angles as written, likewise.
    local_angles_source: tuple[Any, Any, Any] = (None, None, None)


def placements(instr, fold) -> dict[str, Placement]:
    """Resolve every component's placement, in declaration order.

    `fold` turns an `Expr` into a number -- see `niess.scaffold.fold.folder`.

    McCode guarantees a placement reference points *backwards* in `instr.components`, so
    one forward pass is enough and every reference is already resolved when it is needed.
    The references themselves are `Instance` objects rather than names.

    `at_relative` and `rotate_relative` are independent: `AT (...) RELATIVE a ROTATED
    (...) RELATIVE b` is legal McStas and appears in real files, so the two are resolved
    separately rather than assuming one reference for both.
    """
    resolved: dict[str, Placement] = {}

    for instance in instr.components:
        at_vector, at_reference = instance.at_relative
        angles, rotate_reference = instance.rotate_relative

        local = vector(
            [fold(x, f'{instance.name} AT') for x in at_vector], unit='m'
        )
        turn = tuple(fold(a, f'{instance.name} ROTATED') for a in angles)
        rotation = mccode_quaternion(*turn)

        if at_reference is None:
            position = local
        else:
            against = resolved[at_reference.name]
            position = at_relative(against.position, against.orientation, local)

        if rotate_reference is None:
            orientation = rotation
        else:
            orientation = resolved[rotate_reference.name].orientation * rotation

        resolved[instance.name] = Placement(
            position=position,
            orientation=orientation,
            at_reference=None if at_reference is None else at_reference.name,
            rotate_reference=None if rotate_reference is None else rotate_reference.name,
            local_position=local,
            local_angles=turn,
            local_position_source=tuple(at_vector),
            local_angles_source=tuple(angles),
        )

    return resolved


def calibration(instance, placement: Placement, extra: dict[str, Any] | None = None) -> dict:
    """The calibration dictionary entry for one component.

    `name`, `position` and `orientation` are what every niess component's
    `from_calibration` reads; `extra` is whatever its own class adds.
    """
    entry = {
        'name': instance.name,
        'position': placement.position,
        'orientation': placement.orientation,
    }
    entry.update(extra or {})
    return entry
