"""The teaching instrument's structure.

A ``Section`` is a declaration, not code: an ordered list of typed fields naming the
components in beam order. ``Section.from_calibration`` walks those fields, hands each
one its slice of the calibration dictionary, and constructs them **positionally** --
so the declaration order here *is* the beam order, and it must match the key order in
:func:`niess.teaching.parameters.teaching_parameters`.
"""
from ..components import (
    Component, DiscChopper, ESSModerator, FissionChamber, Jaw, Section, StraightGuide,
)
from ..utilities import calibration


# --8<-- [start:sections]
class Guides(Section):
    """Two straight guide units.

    Being its own ``Section`` puts these into a nested instrument: ``to_mccode``
    wraps them in ``assembler.included('teaching_guides')``, so the emitted McStas is a
    ``%include`` rather than two more lines in the top-level TRACE.
    """
    unit_1: StraightGuide
    unit_2: StraightGuide


class Primary(Section):
    """The whole teaching instrument, from moderator to sample position."""
    moderator: ESSModerator
    guides: Guides
    chopper: DiscChopper
    jaw: Jaw
    monitor: FissionChamber
    sample_origin: Component

    # Emit into the caller's assembler rather than nesting the whole instrument inside
    # itself. Underscored fields are Section extras rather than components, so they are
    # invisible to parts()/types()/items(); this one is declared last only because it
    # has a default, and msgspec requires those after the fields that do not.
    _flat: bool = True
    # --8<-- [end:sections]

    @classmethod
    @calibration
    def from_calibration(cls, parameters: dict):
        """Build from a calibration dictionary, defaulting to the shipped one."""
        from .parameters import teaching_parameters
        if len(parameters) == 0:
            parameters = teaching_parameters()
        return super().from_calibration(parameters)
