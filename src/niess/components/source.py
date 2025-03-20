from __future__ import annotations

from dataclasses import dataclass
from scipp import Variable

from mccode_antlr.common.parameters import InstrumentParameter
from .component import Component


ESS_SOURCE_DURATION = Variable(values=2.857e-3, unit='s', dims=None)



@dataclass
class Source(Component):
    pass


@dataclass
class ESSource(Source):
    """Representation of the ESS Butterfly source

    https://github.com/mccode-dev/McCode/blob/main/mcstas-comps/sources/ESS_butterfly.comp
    """
    sector: str
    beamline: int
    height: Variable
    cold_frac: float
    focus_distance: Variable | None
    focus_width: Variable | None
    focus_height: Variable | None
    cold_performance: float
    thermal_performance: float
    wavelength_minimum: Variable | InstrumentParameter | None
    wavelength_maximum: Variable | InstrumentParameter | None
    latest_emission_time: Variable | None
    n_pulses: int | None
    accelerator_power: Variable | None

    @classmethod
    def from_calibration(cls, cal: dict):
        from scipp import vector as v, scalar as s
        from scipp.spatial import rotations_from_rotvecs as r
        name = cal.get('name', 'ESS_source')
        position = cal.get('position', v([0, 0, 0.], unit='m'))
        orientation = cal.get('orientation', r(v([0, 0, 0.], unit='rad')))

        sector = cal.get('sector', 'W')
        beamline = cal.get('beamline', 4)
        height = cal.get('height', s(3.0, unit='cm'))
        cold_frac = cal.get('cold_fraction', 0.5)
        focus_distance = cal.get('focus_distance', None)
        focus_width = cal.get('focus_width', None)
        focus_height = cal.get('focus_height', None)
        cold_performance = cal.get('cold_performance', 1.0)
        thermal_performance = cal.get('thermal_performance', 1.0)
        wavelength_minimum = cal.get('wavelength_minimum', None)
        wavelength_maximum = cal.get('wavelength_maximum', None)
        if isinstance(wavelength_minimum, str):
            wavelength_minimum = InstrumentParameter.parse(wavelength_minimum)
        if isinstance(wavelength_maximum, str):
            wavelength_maximum = InstrumentParameter.parse(wavelength_maximum)
        latest_emission_time = cal.get('latest_emission_time', None)
        n_pulses = cal.get('n_pulses', None)
        accelerator_power = cal.get('accelerator_power', None)

        return cls(name, position, orientation, sector, beamline, height, cold_frac,
                   focus_distance, focus_width, focus_height, cold_performance,
                   thermal_performance, wavelength_minimum, wavelength_maximum,
                   latest_emission_time, n_pulses, accelerator_power)

    def __mccode__(self) -> tuple[str, dict]:
        from ..utilities import variable_value_or_parameter as value_or
        pars = {
            'sector': '"' + self.sector.strip('"') + '"',
            'beamline': self.beamline,
            'yheight': self.height.to(unit='m').value,
            'cold_frac': self.cold_frac,
            'c_performance': self.cold_performance,
            't_performance': self.thermal_performance,
        }
        if all(x is not None for x in (self.focus_width, self.focus_height, self.focus_distance)):
            pars['dist'] = self.focus_distance.to(unit='m').value
            pars['focus_xw'] = self.focus_width.to(unit='m').value
            pars['focus_yh'] = self.focus_height.to(unit='m').value
        if all(x is not None for x in (self.wavelength_minimum, self.wavelength_maximum)):
            pars['Lmin'] = value_or(self.wavelength_minimum, 'angstrom')
            pars['Lmax'] = value_or(self.wavelength_maximum, 'angstrom')
        if self.latest_emission_time is not None:
            multiplier = self.latest_emission_time.to(unit=ESS_SOURCE_DURATION.unit) / ESS_SOURCE_DURATION
            pars['tmax_multiplier'] = multiplier.value
        if self.n_pulses is not None:
            pars['n_pulses'] = self.n_pulses
        if self.accelerator_power is not None:
            pars['power'] = self.accelerator_power.to(unit='MW').value

        return 'ESS_butterfly', pars
