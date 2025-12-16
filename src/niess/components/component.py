from __future__ import annotations

import msgspec
from typing import ClassVar, Type
from scipp import Variable
from networkx import DiGraph
from mccode_antlr.assembler import Assembler
from mccode_antlr.instr import Instance

# TODO: Add a 'tag' property to either Base or Component
#       This is intended to represent an ESS Facility Breakdown Structure (FBS) tag,
#       and should take precedence over 'name' for the purpose of making component graphs

class Base(msgspec.Struct):
    __struct_field_types__: ClassVar[dict[str, Type]]

    def to_dict(self):
        return {k: getattr(self, k) for k in self.__struct_fields__}

    @classmethod
    def from_dict(cls, data):
        for k, t in cls.__struct_field_types__.items():
            if k not in data:
                raise KeyError(f"{k} not found in data")
            if not isinstance(data[k], t) and isinstance(data[k], dict) and hasattr(t, 'from_dict'):
                data[k] = t.from_dict(data[k])
        return cls(**data)

    def fields(self):
        return self.__struct_fields__

    def __eq__(self, other):
        from scipp import identical
        if not isinstance(other, type(self)):
            return False
        for field in self.__struct_fields__:
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

    def add_to_graph(self, upstream: str | None, name: str, graph: DiGraph):
        graph.add_node(name)
        if upstream is not None:
            graph.add_edge(upstream, name)
        return [name]


class Component(Base, kw_only=True):
    """Any component in the instrument.

    Note
    ----
    If an inheriting class adds an 'offset' attribute to the component, the
    position reported for McStas/McXtrace/McCode has that offset added to position

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

    def to_mccode(
            self, assembler: Assembler,
            at: Instance | str | None = None, rotate: Instance | str | None = None,
    ):
        from mccode_antlr.common.parameters import InstrumentParameter as InstPar
        from ..spatial import mccode_ordered_angles
        from ..mccode import ensure_runtime_parameter

        comp, pars = self.__mccode__()

        if len(pairs:=[(k, x) for k, x in pars.items() if isinstance(x, InstPar)]):
            for name, value in pairs:
                ensure_runtime_parameter(assembler, value)
                pars[name] = str(value)

        at_rel = 'ABSOLUTE' if at is None else at
        rot_rel = 'ABSOLUTE' if rotate is None else rotate

        at = self.position
        if hasattr(self, 'offset'):
            at += getattr(self, 'offset')
        at = (at.to(unit='m').value, at_rel)
        rot = (mccode_ordered_angles(self.orientation), rot_rel)

        return assembler.component(self.name, comp, at=at, rotate=rot, parameters=pars)
