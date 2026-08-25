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

from typing import Optional

from scipp import Variable

from .component import Base


def _zero():
    from scipp import vector
    return vector([0., 0., 0.], unit='m')


def _no_turn():
    from scipp import vector
    return vector([0., 0., 0.], unit='degree')


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
    relative_to:
        The label of a sibling to measure from, instead of the enclosing frame.
    """
    name: str
    position: Variable = None
    rotation: Variable = None
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

    def angles(self) -> tuple[float, float, float]:
        """The turn as McCode-ordered angles: extrinsic x, then y, then z, in degrees.

        A rotation about one axis is that angle on that axis, exactly. Only a rotation
        about several needs composing, and only then is a quaternion involved -- which
        is what keeps a declared forty-degree turn emitting as forty degrees.
        """
        from scipp.spatial import rotations_from_rotvecs
        from ..spatial import mccode_ordered_angles
        values = [float(v) for v in self.rotation.to(unit='degree').value]
        turning = [i for i, v in enumerate(values) if v]
        if len(turning) <= 1:
            return tuple(values)
        return mccode_ordered_angles(rotations_from_rotvecs(self.rotation))

    def orientation(self):
        """The turn as a scipp rotation, for anything that wants to compose it."""
        from scipp.spatial import rotations_from_rotvecs
        return rotations_from_rotvecs(self.rotation)

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
        from ..provenance import add_niess_metadata
        context = visit.context
        assembler = context.assembler

        reference = context.reference(visit.frame)
        if self.relative_to is not None:
            reference = context.reference(f'{visit.parent.id}/{self.relative_to}')

        instance = assembler.component(
            visit.name, 'Arm',
            at=(self.position.to(unit='m').value, reference),
            rotate=(self.angles(), reference))
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
