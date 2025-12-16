from typing import Optional, Union

from scipp import Variable
from mccode_antlr.instr import Instance
from mccode_antlr.common.parameters import InstrumentParameter
from mccode_antlr.assembler import Assembler
from .component import Component


ESS_SOURCE_DURATION = Variable(values=2.857e-3, unit='s', dims=None)



class Source(Component):
    pass


class ESSource(Source):
    """Representation of the ESS Butterfly source

    https://github.com/mccode-dev/McCode/blob/main/mcstas-comps/sources/ESS_butterfly.comp
    """
    sector: str
    beamline: int
    height: Variable
    cold_frac: float
    focus_distance: Optional[Variable]
    focus_width: Optional[Variable]
    focus_height: Optional[Variable]
    cold_performance: float
    thermal_performance: float
    wavelength_minimum: Optional[Union[Variable, InstrumentParameter]]
    wavelength_maximum: Optional[Union[Variable, InstrumentParameter]]
    latest_emission_time: Optional[Variable]
    n_pulses: Optional[int]
    accelerator_power: Optional[Variable]

    @classmethod
    def from_calibration(cls, cal: dict):
        from scipp import vector as v, scalar as s
        from scipp.spatial import rotations_from_rotvecs as r
        from niess.io.mccode import reconstitute_instrument_parameter as rip
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
        wavelength_minimum = rip(cal.get('wavelength_minimum', None), (Variable,))
        wavelength_maximum = rip(cal.get('wavelength_maximum', None), (Variable,))
        latest_emission_time = cal.get('latest_emission_time', None)
        n_pulses = cal.get('n_pulses', None)
        accelerator_power = cal.get('accelerator_power', None)

        return cls(
            name=name,
            position=position,
            orientation=orientation,
            sector=sector,
            beamline=beamline,
            height=height,
            cold_frac=cold_frac,
            focus_distance=focus_distance,
            focus_width=focus_width,
            focus_height=focus_height,
            cold_performance=cold_performance,
            thermal_performance=thermal_performance,
            wavelength_minimum=wavelength_minimum,
            wavelength_maximum=wavelength_maximum,
            latest_emission_time=latest_emission_time,
            n_pulses=n_pulses,
            accelerator_power=accelerator_power
        )

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
            pars['acc_power'] = self.accelerator_power.to(unit='MW').value

        return 'ESS_butterfly', pars

    def to_mccode(
            self, assembler: Assembler,
            at: Instance | str | None = None, rotate: Instance | str | None = None,
    ):
        from ..mccode import ensure_runtime_parameter
        for field in self.fields():
            p = getattr(self, field)
            if isinstance(p, InstrumentParameter):
                ensure_runtime_parameter(assembler, p)
        return super().to_mccode(assembler, at, rotate)

