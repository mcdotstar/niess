from dataclasses import dataclass
from scipp import Variable
from mccode_antlr.assembler import Assembler


@dataclass
class Component:
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
    """
    name: str
    position: Variable
    orientation: Variable

    @classmethod
    def from_calibration(cls, calibration: dict):
        name = calibration['name']
        position = calibration['position']
        orientation = calibration['orientation']
        return cls(name, position, orientation)

    def __mccode__(self) -> tuple[str, dict]:
        """Return the component type name and parameters needed to produce a McCode instance"""
        return 'Arm', {}

    def to_mccode(self, assembler: Assembler):
        from mccode_antlr.common.parameters import InstrumentParameter as InstPar
        from ..spatial import mccode_ordered_angles
        from ..mccode import ensure_runtime_parameter

        comp, pars = self.__mccode__()

        if len(pairs:=[(k, x) for k, x in pars.items() if isinstance(x, InstPar)]):
            for name, value in pairs:
                ensure_runtime_parameter(assembler, value)
                pars[name] = str(value)

        at = self.position
        if hasattr(self, 'offset'):
            at += getattr(self, 'offset')
        at = at.to(unit='m').value
        rot = mccode_ordered_angles(self.orientation)

        return assembler.component(self.name, comp, at=at, rotate=rot, parameters=pars)