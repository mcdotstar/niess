from __future__ import annotations

import msgspec
from msgspec.structs import fields
from functools import lru_cache
from scipp import Variable
from mccode_antlr.assembler import Assembler
from mccode_antlr.instr import Instance

# TODO: Add a 'tag' property to either Base or Component
#       This is intended to represent an ESS Facility Breakdown Structure (FBS) tag,
#       and should take precedence over 'name' for the purpose of making component graphs

class Base(msgspec.Struct):

    @classmethod
    @lru_cache(maxsize=None)
    def fields(cls):
        return [fi.name for fi in fields(cls)]

    @classmethod
    @lru_cache(maxsize=None)
    def types(cls):
        """Get the ordered list of component types which make up this Section"""
        return [fi.type for fi in fields(cls)]

    @classmethod
    @lru_cache(maxsize=None)
    def items(cls):
        """Get the ordered list of component names and types which make up this Section"""
        return [(n, t) for n, t in zip(cls.fields(), cls.types())]

    def to_dict(self):
        return {k: getattr(self, k) for k in self.fields()}

    @classmethod
    def from_dict(cls, data):
        for k, t in cls.items():
            if k not in data:
                raise KeyError(f"{k} not found in data")
            if not isinstance(data[k], t) and isinstance(data[k], dict) and hasattr(t, 'from_dict'):
                data[k] = t.from_dict(data[k])
        return cls(**data)

    def __eq__(self, other):
        from scipp import identical
        if not isinstance(other, type(self)):
            return False
        for field in self.fields():
            a = getattr(self, field)
            b = getattr(other, field)
            if a is None or b is None:
                if a is not None or b is not None:
                    return False
            elif isinstance(a, Variable):
                if not identical(a, b, equal_nan=True):
                    return False
            else:
                if a != b:
                    return False
        return True

    def __niess_children__(self):
        """This object's child components, in declaration order.

        See :mod:`niess.tree`. Overriding is a last resort: the default describes every
        composite in the codebase except one.
        """
        from ..tree import default_children
        return default_children(self)

    def __niess_flow__(self, graph, path):
        """How particle flow passes through this object. See :mod:`niess.tree`."""
        from ..tree import chain_flow
        return chain_flow(self, graph, path)

    def to_graph(self):
        """The particle flow through this object, as a networkx DiGraph."""
        from ..tree import flow_graph
        return flow_graph(self)


class Component(Base, kw_only=True):
    """Any component in the instrument.

    Note
    ----
    If an inheriting class overrides `__mccode_offset__`, the position reported
    for McStas/McXtrace/McCode has that displacement added to position

    Parameters
    ----------
    name: str
        The (unique) name of the component instance
    position: Vector
        The position of the component instance in a global coordinate system. This
        may differ from the position required for, e.g., McStas (see 'offset' Note).
    orientation: Quaternion
        The orientation of the component instance in scipp quaternion form. This
        transforms the coordinate system of the component into the global coordinate
        system.
    tag: str | None
        The Facility Breakdown Structure (FBS) tag representing this component
    """
    name: str
    position: Variable
    orientation: Variable
    # tag: str | None = None

    @classmethod
    def from_calibration(cls, calibration: dict):
        name = calibration['name']
        position = calibration['position']
        orientation = calibration['orientation']
        # tag = calibration.get('tag')
        # return cls(name=name, position=position, orientation=orientation, tag=tag)
        return cls(name=name, position=position, orientation=orientation)

    @classmethod
    def from_dict(cls, dictionary):
        return cls.from_calibration(dictionary)

    def __mccode__(self) -> tuple[str, dict]:
        """Return the component type name and parameters needed to produce a McCode instance"""
        return 'Arm', {}

    def __mccode_role__(self) -> str:
        return 'physical-component'

    def __mccode_extra__(self) -> dict[str, Any]:
        return {}

    def __mccode_offset__(self) -> Variable:
        """Displacement from ``position`` to the point the emitted ``AT`` sits on.

        ``position`` is where the component *is*; a McCode component's origin is not
        always the same point -- a disc chopper's is on the beam while its position is the
        spindle -- so this is what converts between them.

        Zero here, and overridden where it is not. It used to read an ``offset`` attribute
        off whatever component happened to have one, which is a trap: ``PartialEllipse``
        has an ``offset`` too, meaning a distance along the major axis, and it is only
        spared because it is not a Component.
        """
        from scipp import vector
        # in `position`'s own unit: a calibration may measure in mm, and scipp will not
        # add a length in metres to one in millimetres
        return vector([0., 0., 0.], unit=self.position.unit)

    def __mccode_orientation__(self) -> Variable:
        """The rotation the emitted ``ROTATED`` carries.

        ``orientation`` unless a subclass needs the emitted component turned relative to
        the object it describes.
        """
        return self.orientation

    def __mccode_frame_rotation__(self) -> tuple[float, float, float]:
        """The turn from this object's own frame to the one it is emitted in.

        ``__mccode_orientation__`` may differ from ``orientation`` where a McCode
        component's conventions demand it -- a disc chopper's disc always hangs below its
        component origin, so the whole component is turned for the disc to land on the
        right side of the beam. That turn is a modelling artefact of the target, not a
        rotation of the thing, and an adapter reading the emitted instrument cannot tell
        the two apart unless it is written down. This is where it is written down.

        A rotation vector in degrees, whose direction is the axis and whose length is the
        angle. Zero for everything that does not override ``__mccode_orientation__``.
        """
        from scipy.spatial.transform import Rotation
        emitted = Rotation.from_quat(self.__mccode_orientation__().value)
        physical = Rotation.from_quat(self.orientation.value)
        return tuple(float(a) for a in (physical.inv() * emitted).as_rotvec(degrees=True))

    def to_mccode(
            self, assembler: Assembler,
            at: Instance | str | None = None, rotate: Instance | str | None = None,
            insert_provenance_metadata: bool = True,
    ):
        from mccode_antlr.common.parameters import InstrumentParameter as InstPar
        from ..spatial import mccode_ordered_angles
        from ..mccode import add_niess_metadata, ensure_runtime_parameter

        comp, pars = self.__mccode__()

        if len(pairs:=[(k, x) for k, x in pars.items() if isinstance(x, InstPar)]):
            for name, value in pairs:
                ensure_runtime_parameter(assembler, value)
                pars[name] = str(value)

        at_rel = 'ABSOLUTE' if at is None else at
        rot_rel = 'ABSOLUTE' if rotate is None else rotate

        # `+` rather than `+=`: scipp adds in place, and `self.position` is the very
        # Variable the calibration dictionary holds, so `+=` would shift both this
        # component and the calibration it came from -- accumulating another offset
        # on every subsequent build from the same data.
        at = ((self.position + self.__mccode_offset__()).to(unit='m').value, at_rel)
        rot = (mccode_ordered_angles(self.__mccode_orientation__()), rot_rel)

        instance = assembler.component(self.name, comp, at=at, rotate=rot, parameters=pars)
        if insert_provenance_metadata:
            return add_niess_metadata(
                instance,
                self,
                role=self.__mccode_role__(),
                extra=self.__mccode_extra__(),
            )
        return instance
