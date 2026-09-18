from __future__ import annotations

from scipp import Variable
from .component import Component
from mccode_antlr.assembler import Assembler
from mccode_antlr.instr import Instance


class Filter(Component):
    composition: str | None
    temperature: Variable

    @classmethod
    def from_calibration(cls, cal: dict):
        from scipp import scalar as s, vector as v
        from scipp.spatial import rotations_from_rotvecs as r
        name = cal['name']
        composition = cal.get('composition')
        temperature = cal.get('temperature')
        position = cal.get('position', v([0, 0, 0.], unit='m'))
        orientation = cal.get('orientation', r(v([0, 0, 0.], unit='deg')))
        return cls(
            name=name,
            composition=composition,
            temperature=temperature,
            position=position,
            orientation=orientation
        )

    @property
    def cfg(self):
        if self.composition is None:
            return '""'
        if '.ncmat' in self.composition:
            sample = self.composition
        else:
            sample = f'{self.composition}.ncmat'
        if ';temp=' not in sample:
            sample = f'{sample};temp={self.temperature:c}'.replace(' ', '')
        return '"' + sample + '"'


class NCrystalFilter(Filter):
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
        params['cfg'] = self.cfg
        # TODO: Consider also setting (wavelength|energy|wavenumber) limits for
        #       INITIALIZE calculated transmission data -- Filter_sample uses
        #       wavelength and 'sensible' defaults without any specified.
        return 'Filter_sample', params

    def to_mccode(
            self, assembler: Assembler,
            at: Instance | str | None = None, rotate: Instance | str | None = None,
            insert_provenance_metadata: bool = True,
    ):
        """Overload to ensure the registry we need is present"""
        from niess.assembler import ensure_registry
        ensure_registry(assembler, 'mcdotstar/mcstas-radial-filter-collimator@main')
        comp = super().to_mccode(assembler, at, rotate, insert_provenance_metadata=insert_provenance_metadata)
        return comp



class OrderedFilter(NCrystalFilter):
    """(likely) A Bragg scattering filter, e.g., Pyrolytic Graphite"""
    tau: Variable # the direction and lattice spacing used in the filter


class Attenuator(NCrystalFilter):
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
            insert_provenance_metadata: bool = True,
    ):
        from mccode_antlr.common import InstrumentParameter, Expr
        parameter = InstrumentParameter.parse(f"int {self.name}_in = 0")
        assembler.instrument.add_parameter(parameter, ignore_repeated=True)
        comp = super().to_mccode(assembler, at, rotate, insert_provenance_metadata=insert_provenance_metadata)
        comp.WHEN(Expr.parameter(parameter.name))
        return comp


class RadialFilterCollimator(Filter):
    """A combination radial collimator and filter, as used on, e.g., BIFROST

    Typically the fitler material should be beryllium, but other options may prove
    useful in the future.
    """
    height: Variable
    filter_inner_radius: Variable
    filter_outer_radius: Variable
    collimator_inner_radius: Variable
    collimator_outer_radius: Variable
    angle_width: Variable
    collimation_angle: Variable

    @classmethod
    def from_calibration(cls, cal: dict):
        from scipp import vector as v
        from scipp.spatial import rotations_from_rotvecs as r
        name = cal['name']
        height = cal.get('height')
        inner_radius = cal.get('inner_radius')
        outer_radius = cal.get('outer_radius')
        filter_inner_radius = cal.get('filter_inner_radius', inner_radius)
        filter_outer_radius = cal.get('filter_outer_radius', outer_radius)
        collimator_inner_radius = cal.get('collimator_inner_radius', inner_radius)
        collimator_outer_radius = cal.get('collimator_outer_radius', outer_radius)
        angle_width = cal.get('angle_width')
        channel_count = cal.get('channel_count', 1)
        collimation_angle = cal.get('collimation_angle', angle_width / channel_count)
        composition = cal.get('composition')
        temperature = cal.get('temperature')
        position = cal.get('position', v([0, 0, 0.], unit='m'))
        orientation = cal.get('orientation', r(v([0, 0, 0.], unit='deg')))
        return cls(
            name=name,
            height=height,
            filter_inner_radius=filter_inner_radius,
            filter_outer_radius=filter_outer_radius,
            collimator_inner_radius=collimator_inner_radius,
            collimator_outer_radius=collimator_outer_radius,
            angle_width=angle_width,
            collimation_angle=collimation_angle,
            composition=composition,
            temperature=temperature,
            position=position,
            orientation=orientation
        )

    def __mccode__(self) -> tuple[str, dict]:
        params = {
            "yheight": self.height.to(unit='m').value,
            "filter_minimum_radius": self.filter_inner_radius.to(unit='m').value,
            "filter_maximum_radius": self.filter_outer_radius.to(unit='m').value,
            "collimator_minimum_radius": self.collimator_inner_radius.to(unit='m').value,
            "collimator_maximum_radius": self.collimator_outer_radius.to(unit='m').value,
            "angle_width": self.angle_width.to(unit='deg').value,
            "collimation": self.collimation_angle.to(unit='deg').value,
            "cfg": self.cfg,
        }
        # TODO: Consider also setting (wavelength|energy|wavenumber) limits for
        #       INITIALIZE calculated transmission data -- Radial_col_filter uses
        #       wavelength and 'sensible' defaults without any specified.
        return 'Radial_col_filter', params

    def to_mccode(
            self, assembler: Assembler,
            at: Instance | str | None = None, rotate: Instance | str | None = None,
            insert_provenance_metadata: bool = True,
    ):
        """Overload to ensure the registry we need is present"""
        from niess.assembler import ensure_registry
        ensure_registry(assembler, 'mcdotstar/mcstas-radial-filter-collimator@main')
        comp = super().to_mccode(assembler, at, rotate, insert_provenance_metadata=insert_provenance_metadata)
        return comp


def make_aluminum(name, position, orientation, width, height, length):
    from scipp import scalar
    return NCrystalFilter(
        name=name, position=position, orientation=orientation,
        width=width, height=height, length=length,
        composition='Al_sg225', temperature=scalar(300, unit='K')
    )
