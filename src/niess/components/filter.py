from __future__ import annotations

from dataclasses import dataclass
from scipp import Variable
from .component import Component


@dataclass
class Attenuator(Component):
    """Only reduces beam intensity without modifying, e.g., divergence

    Use, e.g., Filter with 'AcrylicGlass_C5O2H8' or 'Polycarbonate_C16O3H14'
    NCrystal materials if more-accurate incoherent scattering (from Acrylic or
    Polycarbonate) is desired.
    """
    transmission: Variable


@dataclass
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
        return cls(name, position, orientation, width, height, length, composition, temperature)

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


@dataclass
class OrderedFilter(Filter):
    """(likely) A Bragg scattering filter, e.g., Pyrolytic Graphite"""
    tau: Variable # the direction and lattice spacing used in the filter


def make_aluminum(name, position, orientation, width, height, length):
    return Filter(name, position, orientation, width, height, length, 'Al_sg225')
