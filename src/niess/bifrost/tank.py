from dataclasses import dataclass
from niess.utilities import calibration

from niess import He3Tube

def _tube_at(distance, rotation_y, length, radius, resistivity, elements, pressure):
    from scipp import vector
    from scipp.spatial import rotations_from_rotvecs
    y, z = vector([0, 1, 0]), vector([0, 0, 1])
    r = rotations_from_rotvecs(y * rotation_y)
    pos = r * (z * distance)
    top = pos + length * y / 2
    bottom = pos - length * y / 2
    return He3Tube(at=bottom, to=top, radius=radius, resistivity=resistivity, elements=elements, pressure=pressure)


def _elastic_monitor_from_params(params):
    from scipp import scalar
    # There is a possibility that some or all necessary parameters are missing
    # but there are not always good defaults to provide in all cases. What do we do?
    distance = params.get('sample_elastic_monitor_distance', scalar(0., unit='m'))
    angle = params.get('tank_elastic_monitor_angle', scalar(0., unit='deg'))
    length = params.get('elastic_monitor_length', scalar(0., unit='m'))
    radius = params.get('elastic_monitor_radius', params.get('elastic_monitor_width', scalar(0., unit='m') / 2))
    resistivity = scalar(1., unit='Ohm/cm')
    pressure = params.get('elastic_monitor_pressure', scalar(1., unit='atm'))
    mon = _tube_at(distance, angle, length, radius, resistivity, 1, pressure)
    return mon


@dataclass
class Tank:
    from scipp import Variable
    from .channel import Channel
    from mccode_antlr.assembler import Assembler
    from mccode_antlr.instr import Instance

    channels: tuple[Channel, ...]
    monitor: He3Tube

    @staticmethod
    @calibration
    def from_calibration(params: dict):
        from scipp import array, scalar
        from .channel import Channel

        channel_params = [{'variant': x} for x in ('s', 'm', 'l')]
        channel_params = {i: channel_params[i % 3] for i in range(9)}
        # but this can be overridden by specifying an integer-keyed dictionary with the parameters for each channel
        channel_params = params.get('channel_params', channel_params)
        # The central a4 angle for each channel, relative to the reference tank angle
        angles = params.get('angles',
                            array(values=[-40, -30, -20, -10, 0, 10, 20, 30, 40.], unit='degree', dims=['channel']))

        channels = [Channel.from_calibration(angles[i], **channel_params[i]) for i in range(9)]
        return Tank(tuple(channels), _elastic_monitor_from_params(params))

    @staticmethod
    def unique_from_calibration(**params):
        from scipp import array
        from .channel import Channel
        channel_params = [{'variant': x} for x in ('s', 'm', 'l')]
        channel_params = {i: channel_params[i % 3] for i in range(3)}
        # but this can be overridden by specifying an integer-keyed dictionary with the parameters for each channel
        channel_params = params.get('channel_params', channel_params)
        # The central a4 angle for each channel, relative to the reference tank angle
        angles = params.get('angles',
                            array(values=[-40, -30, -20, -10, 0, 10, 20, 30, 40.], unit='degree', dims=['channel']))

        channels = [Channel.from_calibration(angles[i], **channel_params[i]) for i in range(3)]
        return Tank(tuple(channels), _elastic_monitor_from_params(params))

    def to_secondary(self, **params):
        from scipp import vector
        from ..components import IndirectSecondary

        sample_at = params.get('sample', vector([0, 0, 0.], unit='m'))

        detectors = []
        analyzers = []
        a_per_d = []
        for channel in self.channels:
            for arm in channel.pairs:
                analyzers.append(arm.analyzer.central_blade)
                detectors.extend(arm.detector.tubes)
                a_per_d.extend([len(analyzers) - 1 for _ in arm.detector.tubes])

        from scipp import arange
        nc = len(self.channels)
        np = len(self.channels[0].pairs)
        a = arange(start=0, stop=len(analyzers), dim='n').fold('n', sizes={'channel': nc, 'pair': np})
        d = arange(start=0, stop=len(detectors), dim='n').fold('n', sizes={'channel': nc, 'pair': np, 'tube': 3})

        return IndirectSecondary(detectors, analyzers, a_per_d, sample_at, a, d)

    def triangulate_detectors(self, unit=None):
        from ..spatial import combine_triangulations
        vts = [channel.triangulate_detectors(unit=unit) for channel in self.channels]
        return combine_triangulations(vts)

    def triangulate_analyzers(self, unit=None):
        from ..spatial import combine_triangulations
        vts = [channel.triangulate_analyzers(unit=unit) for channel in self.channels]
        return combine_triangulations(vts)

    def triangulate(self, unit=None):
        from ..spatial import combine_triangulations
        vts = [channel.triangulate(unit=unit) for channel in self.channels]
        return combine_triangulations(vts)

    def mcstas_parameters(self, sample: Variable):
        from numpy import hstack
        from .combine import combine_parameters
        # pull out the list of 'distances', 'analyzer', 'detector', 'two_theta'
        # from each channel, and stack them into a single array per parameters
        parameters = combine_parameters(self.channels, sample)
        parameters['channel'] = hstack([channel.sample_space_angle(sample).value for channel in self.channels])
        return parameters

    def rtp_parameters(self, sample: Variable):
        from scipp import concat
        return [concat(q, dim='channel') for q in zip(*[c.rtp_parameters(sample) for c in self.channels])]

    def to_mccode(self, assembler: Assembler, sample: Instance, settings: dict = None, **kwargs):
        from scipp import vector, concat, max
        from ..mccode import ensure_user_var
        ensure_user_var(assembler, 'int', 'secondary_cassette', 'Secondary spectrometer analyzer cassette index')

        origin = vector([0, 0, 0], unit='m')
        positions = [c.sample_space_angle(origin).to(unit='radian').value for c in self.channels]
        cov_xy = [c.coverage(origin, unit='radian') for c in self.channels]
        cov_x = 2 * max(concat([y for _, y in cov_xy], dim='channel')).value

        slits_name = 'slits'
        declared_positions = f'{slits_name}_positions'
        assembler.declare_array('double', declared_positions, positions, source=__file__, line=173)
        slits = assembler.component(slits_name, 'Slit_radial_multi', at=((0, 0, 0,), sample))
        slits.set_parameters(slit_width=cov_x, offset='slitAngle*DEG2RAD',
                             number=len(self.channels), radius='slitDistance', height=0.2,
                             positions=declared_positions)
        slits.EXTEND("secondary_cassette = (SCATTERED) ? 1 + slit : -1;")

        for index, channel in enumerate(self.channels):
            name = f"channel_{1 + index}"
            when = f"{1 + index} == secondary_cassette"
            channel.to_mccode(assembler, sample, name=name, when=when, settings=settings, **kwargs)

