from dataclasses import dataclass

from mccode_antlr.assembler import Assembler
from scipp import Variable
from .component import Component

# Monitors used on BIFROST, which are limited within McStas to always produce histograms

def nexus_structure_metadata(topic, *, variables, constants):
    from json import dumps
    from mccode_antlr.common import MetaData
    from mccode_to_kafka.writer import da00_dataarray_config
    # TODO uodate eniius.utils.mccode_component_eniius_data to use ('*', 'application/json') instead of
    #      only ('eniius_data', 'json')
    # The correct JSON to encode is a dictionary with a single key, 'data', which itself is a dictionary with
    # the keys 'type' and 'value'. The value of 'type' is 'dict' and the value of 'value' is the actual NeXus structure.
    # This is very hacky and is (currently) necessary to escape parsing within eniius.

    struct = da00_dataarray_config(topic, source='mccode-to-kafka', variables=variables, constants=constants)

    return MetaData.from_instance_tokens(topic, 'application/json', 'nexus_structure_stream_data', dumps(struct))


def add_frame_monitor_metadata(inst, n):
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
    metadata = nexus_structure_metadata(topic=inst.name, variables=variables,
                                        constants=constants)
    inst.add_metadata(metadata)
    return inst



@dataclass
class FissionChamber(Component):
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
        return cls(name, position, orientation, width, height, thickness)

    def __mccode__(self) -> tuple[str, dict]:
        p = {
            'xwidth': self.width.to(unit='m').value,
            'yheight': self.height.to(unit='m').value,
            'nt': int(1e6 / 14.0 / 7),  # 7 microsecond bins
            'frequency': 14.0,
        }
        return 'Frame_monitor', p

    def to_mccode(self, assembler: Assembler):
        inst = super().to_mccode(assembler)
        # Build the NeXus Structure entry to point to the correct Kafka stream
        return add_frame_monitor_metadata(inst, self.__mccode__()[1]['nt'])


@dataclass
class BeamCurrentMonitor(Component):
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
        return cls(name, position, orientation, width, height, thickness, sample_rate)

    def __mccode__(self) -> tuple[str, dict]:
        from scipp import scalar
        source_frequency = scalar(14.0, unit='Hz')
        nt = int((self.sample_rate.to(unit='Hz') / source_frequency).value)
        p = {
            'xwidth': self.width.to(unit='m').value,
            'yheight': self.height.to(unit='m').value,
            'nt': nt,
            'frequency': source_frequency.to(unit='Hz').value,
        }
        return 'Frame_monitor', p

    def to_mccode(self, assembler: Assembler):
        inst = super().to_mccode(assembler)
        # Build the NeXus Structure entry to point to the correct Kafka stream
        return add_frame_monitor_metadata(inst, self.__mccode__()[1]['nt'])


@dataclass
class GEM2D(Component):
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
        return cls(name, position, orientation, width, height, thickness, x_strips, y_strips)

    def __mccode__(self) -> tuple[str, dict]:
        from scipp import scalar
        source_frequency = scalar(14.0, unit='Hz')
        nt = 1000 # 71.42 µs bins
        p = {
            'xwidth': self.width.to(unit='m').value,
            'yheight': self.height.to(unit='m').value,
            'nt': nt,
            'frequency': source_frequency.to(unit='Hz').value,
        }
        return 'Frame_monitor', p

    def to_mccode(self, assembler: Assembler):
        inst = super().to_mccode(assembler)
        # Build the NeXus Structure entry to point to the correct Kafka stream
        return add_frame_monitor_metadata(inst, self.__mccode__()[1]['nt'])
