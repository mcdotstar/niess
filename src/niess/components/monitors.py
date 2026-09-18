from mccode_antlr.assembler import Assembler
from mccode_antlr.instr.instance import Instance
from scipp import Variable
from .component import Component

# Monitors used on BIFROST, which are limited within McStas to always produce histograms

def nexus_structure_metadata(topic: str, source: str, *, variables, constants):
    from json import dumps
    from mccode_antlr.common import MetaData
    from mccode_to_kafka.writer import da00_dataarray_config

    struct = da00_dataarray_config(topic, source=source, variables=variables, constants=constants)

    return MetaData.from_instance_tokens(topic, 'application/json', 'nexus_structure_stream_data', dumps(struct))


def beam_monitor_topic(instrument: str) -> str:
    """The default Kafka topic carrying an instrument's beam-monitor histograms."""
    return f'{instrument.lower()}_beam_monitor'


def add_monitor_metadata(instr_name: str, inst: Instance, n, topic: str | None = None):
    """Attach a da00 histogram-stream configuration to a monitor instance.

    ``instr_name`` must be the *instrument* name -- use
    :func:`niess.mccode.instrument_name`, not ``assembler.name``, which inside a
    nested section is the section's name. ``topic`` overrides the derived default
    outright, for instruments that publish somewhere else entirely.
    """
    from mccode_to_kafka.writer import da00_variable_config
    axes = {
        'signal': {'unit': 'counts', 'label': f'{inst.name} counts', 'shape': [n]},
        'errors': {'unit': 'counts', 'label': f'{inst.name} count errors',
                   'shape': [n]},
        't': {'unit': 'microsecond', 'label': 'time since reference', 'shape': [n + 1]},
    }
    configs = {
        k: da00_variable_config(**v, name=k, axes=['t'], data_type='float64')
        for k, v in axes.items()
    }
    variables = [configs['signal'], configs['errors']]
    constants = [configs['t']]
    topic = beam_monitor_topic(instr_name) if topic is None else topic
    source = inst.name  # 'cbm1', 'cbm2', etc. in the real instrument, for now
    metadata = nexus_structure_metadata(
        topic=topic, source=source, variables=variables, constants=constants
    )
    inst.add_metadata(metadata)
    return inst


class FrameMonitor(Component, kw_only=True):
    """A monitor that histograms in time.

    ``stream`` says how its data reaches NeXus -- ``{'module': 'ev44', 'topic': ...,
    'source': ...}`` for events, ``da00`` for histograms. Which suits is a property of
    the instrument setup rather than of the monitor, so it is chosen by whoever builds
    the instrument and recorded here. It used to be an argument to ``to_mccode``, which
    meant a target reading the tree could not see it, and a target reading the emitted
    instrument had to find it in a metadata blob.
    """
    stream: dict | None = None

    @staticmethod
    def time_bins():
        return int(1e6 / 14.0 / 7) # 7 microsecond bins

    def to_mccode(
            self, assembler: Assembler,
            at: Instance | str | None = None, rotate: Instance | str | None = None,
            insert_provenance_metadata: bool = True,
            nexus_stream: dict | None = None,
            topic: str | None = None,
    ):
        """Add this monitor to an instrument.

        ``nexus_stream`` chooses how the monitor's data reaches NeXus, e.g.
        ``{'module': 'ev44', 'topic': ..., 'source': ...}``. Which protocol suits a
        given monitor is a property of the instrument setup, so the choice is made
        here, by whoever builds the instrument, and recorded in the provenance
        metadata for :mod:`niess.nexus` to read back. Left unset, the monitor keeps
        its da00 histogram stream.

        ``topic`` overrides the Kafka topic that stream is published on. It defaults
        to ``{instrument}_beam_monitor``, taken from the name of the *root* assembler
        -- naming that assembler is how a different instrument gets a different topic.
        """
        from niess.mccode import add_niess_metadata, ensure_registry, instrument_name
        ensure_registry(assembler, 'mcdotstar/mcstas-frame-tof-monitor@main')

        inst = super().to_mccode(assembler, at, rotate, insert_provenance_metadata=insert_provenance_metadata)
        # The instrument's name, not assembler.name: inside a nested section the
        # latter is the section's own name, which would publish this monitor's data
        # on a per-section topic nobody subscribes to.
        instrument = instrument_name(assembler)

        nexus_stream = self.stream if nexus_stream is None else nexus_stream
        if nexus_stream is None:
            # Default: a da00 histogram stream, described by a METADATA block
            return add_monitor_metadata(instrument, inst, self.time_bins(), topic=topic)

        if insert_provenance_metadata:
            add_niess_metadata(
                inst, self,
                role=self.__mccode_role__(),
                extra=self.__mccode_extra__() | {'nexus_stream': nexus_stream},
            )
        if nexus_stream.get('module') == 'da00' and 'config' not in nexus_stream:
            # da00 wanted, but no configuration given: build the standard one
            return add_monitor_metadata(
                instrument, inst, self.time_bins(),
                topic=topic or nexus_stream.get('topic'),
            )
        return inst

    def __partial__mccode__(self) -> tuple[str, dict]:
        return 'Frame_monitor', {'nt': self.time_bins(), 'frequency': 14.0}


class FissionChamber(FrameMonitor, kw_only=True):
    """Zero-dimensional fission chamber monitor.
    Outputs events without any spatial information.
    """
    width: Variable
    height: Variable
    thickness: Variable

    @classmethod
    def from_calibration(cls, cal: dict):
        name = cal['name']
        position = cal['position']
        orientation = cal['orientation']
        width = cal['width']
        height = cal['height']
        thickness = cal.get('thickness', cal.get('length'))
        return cls(
            name=name,
            position=position,
            orientation=orientation,
            width=width,
            height=height,
            thickness=thickness
        )

    def __mccode__(self) -> tuple[str, dict]:
        t, p = self.__partial__mccode__()
        p.update({
            'xwidth': self.width.to(unit='m').value,
            'yheight': self.height.to(unit='m').value,
        })
        return t, p


class He3Monitor(FrameMonitor, kw_only=True):
    """Zero-dimensional He3 tube monitor.
    Outputs events without any spatial information.
    """
    radius: Variable
    length: Variable
    pressure: Variable

    @classmethod
    def from_calibration(cls, cal: dict):
        name = cal['name']
        position = cal['position']
        orientation = cal['orientation']
        radius = cal['radius']
        length = cal['length']
        pressure = cal['pressure']
        return cls(
            name=name, position=position, orientation=orientation,
            radius=radius, length=length, pressure=pressure
        )

    def __mccode__(self) -> tuple[str, dict]:
        t, p = self.__partial__mccode__()
        p.update({
            'xwidth': 2 * self.radius.to(unit='m').value,
            'yheight': self.length.to(unit='m').value,
        })
        return t, p


class BeamCurrentMonitor(FrameMonitor, kw_only=True):
    """Zero-dimensional beam current monitor.
    Outputs a current sampled at a configurable frequency.
    """
    width: Variable
    height: Variable
    thickness: Variable
    sample_rate: Variable

    @classmethod
    def from_calibration(cls, cal: dict):
        name = cal['name']
        position = cal['position']
        orientation = cal['orientation']
        width = cal['width']
        height = cal['height']
        thickness = cal.get('thickness', cal.get('length'))
        sample_rate = cal.get('sample_rate', cal.get('frequency'))
        if sample_rate is None:
            raise ValueError(f'The sample rate for {name} must be defined')
        return cls(
            name=name, position=position, orientation=orientation,
            width=width, height=height, thickness=thickness, sample_rate=sample_rate
        )

    def time_bins(self):
        from scipp import scalar
        source_frequency = scalar(14.0, unit='Hz')
        return int((self.sample_rate.to(unit='Hz') / source_frequency).value)

    def __mccode__(self) -> tuple[str, dict]:
        t, p = self.__partial__mccode__()
        p.update({
            'xwidth': self.width.to(unit='m').value,
            'yheight': self.height.to(unit='m').value,
        })
        return t, p


class GEM2D(FrameMonitor, kw_only=True):
    """Two-dimensional Gas Electron Multiplier monitor.
    Outputs events on X or Y strips (without coincidence) or at (X, Y) point
    (with coincidence).

    For now the pixelation is ignored and a 0-D no-coincidence frame monitor is output
    """
    width: Variable
    height: Variable
    thickness: Variable
    x_strips: int
    y_strips: int

    @classmethod
    def from_calibration(cls, cal: dict):
        name = cal['name']
        position = cal['position']
        orientation = cal['orientation']
        width = cal['width']
        height = cal['height']
        thickness = cal.get('thickness', cal.get('length'))
        x_strips = cal.get('x_strips', cal.get('nx', 1))
        y_strips = cal.get('y_strips', cal.get('ny', 1))
        return cls(
            name=name, position=position, orientation=orientation,
            width=width, height=height, thickness=thickness,
            x_strips=x_strips, y_strips=y_strips
        )

    def __mccode__(self) -> tuple[str, dict]:
        t, p = self.__partial__mccode__()
        p.update({
            'xwidth': self.width.to(unit='m').value,
            'yheight': self.height.to(unit='m').value,
        })
        return t, p
