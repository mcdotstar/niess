from typing import Optional, Union

from scipp import Variable
from mccode_antlr.instr import Instance
from mccode_antlr.common.parameters import InstrumentParameter
from mccode_antlr.assembler import Assembler
from .component import Component


#: How long the ESS accelerator's proton pulse lasts. The accelerator is the *source*;
#: this is one of its properties, which is why it keeps the name.
ESS_SOURCE_DURATION = Variable(values=2.857e-3, unit='s', dims=None)


class Moderator(Component):
    """Where an instrument's neutrons come from.

    Not the facility's source, which for ESS is the proton accelerator driving the
    spallation target: a moderator is what an instrument views, and the start of every
    flight path. Targets look for this class to find where a path begins.
    """


class ESSModerator(Moderator):
    """The ESS butterfly moderator, as seen from one beamline

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
        name = cal.get('name', 'ESS_moderator')
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
            insert_provenance_metadata: bool = True,
    ):
        from ..assembler import ensure_runtime_parameter
        for field in self.fields():
            p = getattr(self, field)
            if isinstance(p, InstrumentParameter):
                ensure_runtime_parameter(assembler, p)
        return super().to_mccode(assembler, at, rotate, insert_provenance_metadata=insert_provenance_metadata)



class PolygonESSModerator(ESSModerator):
    """The ESS butterfly moderator, emitting only what the chopper train can pass.

    chopper-lib's ``Polygon_ESS_butterfly``: an ``ESS_butterfly`` that works out, at run
    time, the exact region of (inverse velocity, emission time) the chopper train
    transmits, and absorbs -- or with ``resample``, redraws -- every ray outside it.
    Nothing reaching the sample changes; the rays that would have died on a disc are
    simply not spent.

    The component reads the train as a pointer and a count, which `niess.chopcalc`
    publishes under `train_identifier`. So an instrument with this moderator has to be
    narrowed::

        to_mccode(instrument, assembler=assembler)
        narrow_source_wavelengths(assembler, train_from_instrument(instrument))

    which finds the names here and exports under them; without that the instrument does
    not compile.

    https://github.com/mcdotstar/mcstas-chopper-lib/blob/main/Polygon_ESS_butterfly.comp
    """
    chopper_train: Optional[str] = None
    """The C name the train is published under; ``None`` is ``{name}_choppers``."""
    path_spread_fraction: float = 0.0
    """Extra flight path a ray may have taken, as a fraction of each disc's own path."""
    noise_fraction: float = 0.0
    """Accept a ray outside the region with this probability."""
    use_region: bool = True
    """Limit emission to the transmitted region. False makes this an `ESSModerator`."""
    resample: bool = False
    """Redraw a ray outside the region from inside it, correcting its weight."""
    save_polygons: bool = True
    """Write the transmitted region to ``{filename}.json``."""
    verify_acceptance: bool = True
    """Count rays drawn and rays in the region, and report their ratio."""
    filename: Optional[str] = None
    """The base name of the output file; ``None`` is the component's own name."""

    #: The component's own defaults, so only what differs is emitted.
    _COMPONENT_DEFAULTS = {
        'path_spread_fraction': 0.0, 'noise_fraction': 0.0, 'use_region': True,
        'resample': False, 'save_polygons': True, 'verify_acceptance': True,
    }

    @classmethod
    def from_calibration(cls, cal: dict):
        from msgspec.structs import replace
        moderator = super().from_calibration(cal)
        return replace(moderator, **{key: cal[key] for key in (
            'chopper_train', 'filename', *cls._COMPONENT_DEFAULTS) if key in cal})

    def train_identifier(self) -> str:
        """The train's pointer in DECLARE; its count is this with ``_count`` added."""
        return self.chopper_train or f'{self.name}_choppers'

    def __chopcalc_reads_train__(self) -> tuple[str, str]:
        """The names `niess.chopcalc` has to publish the train under for this to compile."""
        return self.train_identifier(), f'{self.train_identifier()}_count'

    def __mccode__(self) -> tuple[str, dict]:
        _, pars = super().__mccode__()
        choppers, count = self.__chopcalc_reads_train__()
        pars['choppers'] = f'(double *) {choppers}'
        pars['chopper_count'] = count
        for field, default in self._COMPONENT_DEFAULTS.items():
            value = getattr(self, field)
            if value != default:
                pars[field] = int(value) if isinstance(value, bool) else value
        if self.filename is not None:
            pars['filename'] = '"' + self.filename.strip('"') + '"'
        return 'Polygon_ESS_butterfly', pars

    def to_mccode(
            self, assembler: Assembler,
            at: Instance | str | None = None, rotate: Instance | str | None = None,
            insert_provenance_metadata: bool = True,
    ):
        from ..assembler import ensure_registry
        # Polygon_ESS_butterfly is chopper-lib's, pinned in one place with the guard
        # that refuses an older library.
        from ..chopcalc.emit import CHOPPER_LIB_REGISTRY
        ensure_registry(assembler, CHOPPER_LIB_REGISTRY)
        return super().to_mccode(assembler, at, rotate,
                                 insert_provenance_metadata=insert_provenance_metadata)
