from __future__ import annotations

from scipp import Variable
from .component import Component
from mccode_antlr.assembler import Assembler
from mccode_antlr.instr import Instance


class Filter(Component):
    """A powder or amorphous material that effects a beam with physics from NCrystal

    Likely useful NCrystal data sets include:
        AcrylicGlass_C5O2H8
        Al_sg225
        Be_sg194
        Polycarbonate_C16O3H14
        C_sg194_pyrolytic_graphite
    """
    width: Variable
    height: Variable
    length: Variable
    composition: str
    temperature: Variable

    @classmethod
    def from_calibration(cls, cal: dict):
        from scipp import scalar as s, vector as v
        from scipp.spatial import rotations_from_rotvecs as r
        name = cal['name']
        width = cal.get('width')
        height = cal.get('height')
        length = cal.get('length')
        composition = cal.get('composition')
        temperature = cal.get('temperature', s(300., unit='K'))
        position = cal.get('position', v([0, 0, 0.], unit='m'))
        orientation = cal.get('orientation', r(v([0.,0, 0], unit='deg')))
        return cls(
            name=name,
            position=position,
            orientation=orientation,
            width=width,
            height=height,
            length=length,
            composition=composition,
            temperature=temperature
        )

    def __mccode__(self) -> tuple[str, dict]:
        params = dict()
        params['xwidth'] = self.width.to(unit='m').value
        params['yheight'] = self.height.to(unit='m').value
        params['zdepth'] = self.length.to(unit='m').value
        if '.ncmat' in self.composition:
            sample = self.composition
        else:
            sample = f'{self.composition}.ncmat'
        if ';temp=' not in sample:
            sample = f'{sample};temp={self.temperature:c}'.replace(' ','')
        params['cfg'] = '"' + sample + '"'
        return 'NCrystal_sample', params


class OrderedFilter(Filter):
    """(likely) A Bragg scattering filter, e.g., Pyrolytic Graphite"""
    tau: Variable # the direction and lattice spacing used in the filter


class Attenuator(Filter):
    """A pneumatically insertable absorbing or scattering material

    Likely materials
    | name                                             | NCrystal dataset         |
    |--------------------------------------------------|--------------------------|
    | Poly(methyl methacrylate)                        |  'AcrylicGlass_C5O2H8'   |
    |  AKA Plexiglass, Lucite, Perspex, acrylic, etc.  |                          |
    | Polycarbonate                                    | 'Polycarbonate_C16O3H14' |
    """
    def to_mccode(
            self, assembler: Assembler,
            at: Instance | str | None = None, rotate: Instance | str | None = None,
    ):
        from mccode_antlr.common import InstrumentParameter, Expr, Value, DataType, ObjectType, ShapeType
        parameter = InstrumentParameter.parse(f"int {self.name}_in = 0")
        assembler.instrument.add_parameter(parameter, ignore_repeated=True)
        comp = super().to_mccode(assembler, at, rotate)
        var = Value(parameter.name, DataType.int, ObjectType.parameter, ShapeType.scalar)
        comp.WHEN(Expr(var))
        return comp


def make_aluminum(name, position, orientation, width, height, length):
    from scipp import scalar
    return Filter(
        name=name, position=position, orientation=orientation,
        width=width, height=height, length=length,
        composition='Al_sg225', temperature=scalar(300, unit='K')
    )
