"""A coordinate frame: a place to hang things.

The BIFROST tank has ninety-nine of these -- one per channel, two per arm -- and until
now they existed only as a side effect of emitting McStas. `Arm.__mccode_enter__` built
them, so the only way to learn that an analyzer sits 1.19 m along its channel and rolled
a quarter turn was to emit a McStas instrument and read it back. Anything else wanting
the same placement had to restate it.

A frame is not a thing in the beam. It has no size, absorbs nothing and scatters nothing,
and a neutron does not pass *through* it -- which is why it is transparent to the flow
graph, and why it is not a Component. It is a statement about where to measure the next
thing from, and each target renders it as it likes: McStas as an `Arm`, NeXus as a link
in a `depends_on` chain, CAD as a node in the assembly tree.

Placement is relative to whatever encloses the frame, unless ``relative_to`` names a
sibling. That is what an arm's second frame needs: it is measured from the analyzer, not
from the arm.
"""
from __future__ import annotations

from typing import Any, Optional

from scipp import Variable

from .component import Base


def _zero():
    from scipp import vector
    return vector([0., 0., 0.], unit='m')


def _no_turn():
    from scipp import vector
    return vector([0., 0., 0.], unit='degree')


def _default_angle(angle) -> float:
    """A declared angle as a number: a knob contributes the value it is declared with."""
    from ..dispatch import expr_float
    value = getattr(angle, 'value', angle)
    try:
        return float(value)
    except (TypeError, ValueError):
        try:
            return expr_float(value)
        except Exception:
            return 0.0


class Frame(Base):
    """Where to measure the next thing from.

    Parameters
    ----------
    name:
        What this frame is called, under whatever contains it.
    position:
        Its offset within the frame it hangs from.
    rotation:
        How it is turned, as a rotation vector in degrees: the direction is the axis and
        the length the angle. Not a quaternion, which is what ``Component.orientation``
        holds, and the difference is deliberate. A component's orientation is *measured*
        -- where the thing actually points -- and a quaternion is the right way to carry
        that. A frame's rotation is *declared*: turn forty degrees about y. Saying it
        that way keeps it exact, where going through a quaternion and back does not --
        eight of BIFROST's nine cassette angles come back differing in the last bit or
        two, which is physically nothing and textually a different instrument.
        A turn a *run* sets is written the other way, as McCode-ordered angles with an
        ``InstrumentParameter`` in the slot it turns about: ``(0, a4, 0)`` is "turn by
        a4 about y, whatever a4 is today". There is no rotation vector for that, because
        there is no angle yet -- which is the point. A target renders it as the knob it
        is: McStas names it in ``ROTATED``, NeXus links the transformation to its
        ``NXlog``, and CAD, which has to draw something, uses the declared default.
    relative_to:
        The label of a sibling to measure from, instead of the enclosing frame.
    """
    name: str
    position: Variable = None
    #: A scipp rotation vector, or McCode-ordered angles that may name run-time knobs.
    rotation: Any = None
    relative_to: Optional[str] = None
    extra: dict = None
    owner_key: Optional[str] = None

    def __post_init__(self):
        if self.position is None:
            self.position = _zero()
        if self.rotation is None:
            self.rotation = _no_turn()
        if self.extra is None:
            self.extra = {}

    def declared_angles(self) -> tuple | None:
        """The McCode-ordered angles, when the turn was declared that way rather than
        as a rotation vector. ``None`` for the vector form."""
        return self.rotation if isinstance(self.rotation, tuple) else None

    def parameters(self) -> tuple:
        """The run-time knobs this frame turns by, if any.

        A target has to declare these before naming them, and it is this frame that
        knows about them -- nothing else in the tree does.
        """
        from mccode_antlr.common import InstrumentParameter
        declared = self.declared_angles()
        if declared is None:
            return ()
        return tuple(a for a in declared if isinstance(a, InstrumentParameter))

    def angles(self) -> tuple:
        """The turn as McCode-ordered angles: extrinsic x, then y, then z, in degrees.

        A rotation about one axis is that angle on that axis, exactly. Only a rotation
        about several needs composing, and only then is a quaternion involved -- which
        is what keeps a declared forty-degree turn emitting as forty degrees.

        An entry may be an ``InstrumentParameter`` rather than a number, in which case
        it stays one: it is a knob, and every target renders a knob differently.
        """
        from scipp.spatial import rotations_from_rotvecs
        from ..spatial import mccode_ordered_angles
        declared = self.declared_angles()
        if declared is not None:
            return declared
        values = [float(v) for v in self.rotation.to(unit='degree').value]
        turning = [i for i, v in enumerate(values) if v]
        if len(turning) <= 1:
            return tuple(values)
        return mccode_ordered_angles(rotations_from_rotvecs(self.rotation))

    def mccode_angles(self) -> tuple:
        """The angles as McStas wants them written: a number, or a knob's name."""
        from mccode_antlr.common import InstrumentParameter
        return tuple(a.name if isinstance(a, InstrumentParameter) else a
                     for a in self.angles())

    def orientation(self):
        """The turn as a scipp rotation, for anything that wants to compose it.

        A knob has no one value, so this uses the one it is declared with -- which is
        what a drawing needs and what a run that sets nothing would get. Anything that
        can express the knob itself should read `angles` and not this.
        """
        from scipp import vector
        from scipp.spatial import rotations_from_rotvecs
        from ..spatial import mccode_ordered_angles
        declared = self.declared_angles()
        if declared is None:
            return rotations_from_rotvecs(self.rotation)
        numbers = [_default_angle(a) for a in declared]
        turning = [i for i, v in enumerate(numbers) if v]
        if len(turning) <= 1:
            axis = [1.0 if i == (turning[0] if turning else 0) else 0.0
                    for i in range(3)]
            angle = numbers[turning[0]] if turning else 0.0
            return rotations_from_rotvecs(
                vector(value=[a * angle for a in axis], unit='degree'))
        # several axes: compose them in McCode's own order, extrinsic x then y then z
        turn = rotations_from_rotvecs(vector(value=[numbers[0], 0., 0.], unit='degree'))
        for index, axis in ((1, [0., 1., 0.]), (2, [0., 0., 1.])):
            step = [a * numbers[index] for a in axis]
            turn = rotations_from_rotvecs(vector(value=step, unit='degree')) * turn
        return turn

    def __niess_label__(self, label: str) -> str:
        """A frame is named, and things measured from it refer to it by that name."""
        return self.name

    def __niess_flow__(self, graph, path):
        """Nothing flows through a frame.

        Reporting no entry and no exit is what makes it transparent: the components
        either side of it chain to each other as though it were not there.
        """
        return (), ()

    def __mccode_leaf__(self, visit):
        """McStas says "measure from here" with an Arm, so that is what this becomes.

        The provenance records the composite the frame belongs to rather than the frame
        itself: a cassette Arm is a feature of the channel that declared it, and that is
        what an adapter reading the instrument back wants to know.
        """
        from ..assembler import ensure_runtime_parameter
        from ..provenance import add_niess_metadata
        context = visit.context
        assembler = context.assembler

        # a frame turned by a knob names it in ROTATED, so the knob has to exist
        for parameter in self.parameters():
            ensure_runtime_parameter(assembler, parameter)

        reference = context.reference(visit.frame)
        if self.relative_to is not None:
            reference = context.reference(f'{visit.parent.id}/{self.relative_to}')

        instance = assembler.component(
            visit.name, 'Arm',
            at=(self.position.to(unit='m').value, reference),
            rotate=(self.mccode_angles(), reference))
        owner = visit.parent
        extra = dict(self.extra)
        if self.owner_key is not None and owner is not None:
            # which channel, which arm: the frame belongs to the thing that declared it
            extra[self.owner_key] = owner.name
        add_niess_metadata(instance, owner.obj if owner is not None else self,
                           source_name=visit.name, role='reference-frame', extra=extra)
        when = context.whens.get(visit.id)
        if when is not None:
            instance.WHEN(when)
        context.emitted[visit.id] = instance.name
        return instance
