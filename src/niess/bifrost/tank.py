from __future__ import annotations

from niess.utilities import calibration
from niess.components import He3Monitor
from niess.components.component import Base

def _origin():
    """The sample position, as a fresh Variable every time.

    Fresh because scipp's in-place operators would let a caller shift a shared one --
    the same trap Component.to_mccode documents for `position + offset`.
    """
    from scipp import vector
    return vector([0, 0, 0], unit='m')


def _elastic_monitor_from_params(params):
    from scipp import vector
    from scipp.spatial import rotations_from_rotvecs
    from .parameters import tank_parameters
    tp = tank_parameters()
    def par_or(par):
        return tp[par] if par not in params else params[par]

    # There is a possibility that some or all necessary parameters are missing
    # but there are not always good defaults to provide in all cases. What do we do?
    distance = par_or('sample_elastic_monitor_distance')
    angle = par_or('tank_elastic_monitor_angle')
    y, z = vector([0, 1, 0]), vector([0, 0, 1])
    ori = rotations_from_rotvecs(y * angle)  # is this the monitor orientation too?

    cal = par_or('elastic_monitor')
    cal['name'] = cal.get('name', 'elastic_monitor')
    cal['position'] = cal.get('position', ori * (z * distance))
    cal['orientation'] = cal.get('orientation', ori)

    return He3Monitor.from_calibration(cal)


class Tank(Base):
    from scipp import Variable
    from networkx import DiGraph
    from .channel import Channel
    from mccode_antlr.assembler import Assembler
    from mccode_antlr.instr import Instance

    # Declaration order is emission order: to_mccode emits the radial slits, then the
    # elastic monitor, then the channels. The walk rewrite derives emission order from
    # the child protocol, so a composite whose fields are declared in a different order
    # from the one it emits in would need an event API rich enough to interleave its own
    # emissions between groups of children -- permanent API surface to preserve one
    # accident. Cheaper to make the declaration honest.
    #
    # The slits themselves have no field yet; they become a component object of their
    # own when the McStas-only artefacts move onto the McStas translator, and they go
    # first when they do.
    monitor: He3Monitor
    channels: tuple[Channel, ...]

    # -- the radial slit geometry ---------------------------------------------
    # What the emitted Slit_radial_multi is built from. It used to be worked out inside
    # to_mccode, which meant the tank reached into every channel's coverage at emission
    # time and no other target could see the result.

    @property
    def channel_angles(self) -> list[float]:
        """Where each channel sits about the sample, in radians."""
        return [c.sample_space_angle(_origin()).to(unit='radian').value
                for c in self.channels]

    @property
    def monitor_angle(self) -> float:
        """Where the elastic (Bragg peak) monitor sits, in radians.

        It is outside the slits and gets a slit of its own, added last -- which is what
        lets the emitted WHEN clause identify it by index.
        """
        from scipp import atan2
        at = self.monitor.position - _origin().to(unit=self.monitor.position.unit)
        return atan2(y=at.fields.x, x=at.fields.z).to(unit='radian').value

    @property
    def slit_angles(self) -> list[float]:
        """Every radial slit opening, in radians: one per channel, then the monitor."""
        return [*self.channel_angles, self.monitor_angle]

    @property
    def slit_width(self) -> float:
        """The angular width shared by every radial slit, in radians.

        Twice the largest vertical analyzer coverage in the tank. Slit_radial_multi
        accepts a neutron within ``slit_width/2`` of a slit angle, and those angles are
        azimuthal, so a *vertical* extent setting an azimuthal opening deserves an
        explanation rather than a `# TODO`.

        In this frame x is along the beam, y is horizontal-transverse and z is vertical:
        the nine channels fan out in x-y with every arm at z = 0. Analyzer.coverage
        builds its own basis from the global vertical rather than from anything McStas
        does, so the 90-degree turn Arm.to_mccode applies when it places the analyzer
        never reaches it, and its second element really is the vertical extent -- 83 mm
        of blade stack against 144 mm of blade width, subtending 4.0 and 7.0 degrees at
        1.19 m.

        Doubling the vertical gives 8.1 degrees, which fits inside the 10-degree channel
        spacing. Twice the analyzer's horizontal coverage (13.9) or twice the detector's
        (11.4) would overlap the neighbouring channels, so the emitted number is the
        workable one of the three. Whether that is deliberate -- a slit sized to clear
        the analyzer's 7.0-degree horizontal acceptance with margin -- or an axis that
        got crossed and landed somewhere sensible anyway is not decidable from the code.
        Either way it is unchanged here: this is a move, not a correction.
        """
        from scipp import concat, max
        coverage = [c.coverage(_origin(), unit='radian') for c in self.channels]
        return 2 * max(concat([y for _, y in coverage], dim='channel')).value

    @classmethod
    def from_dict(cls, data):
        from .channel import Channel
        cs = data['channels']
        if not hasattr(cs, '__len__'):
            raise ValueError('Channels must have length (probably 9)')
        cs = tuple(c if isinstance(c, Channel) else Channel.from_dict(c) for c in cs)
        mn = data['monitor']
        if not isinstance(mn, He3Monitor):
            mn = He3Monitor.from_dict(mn)
        return cls(monitor=mn, channels=cs)

    @staticmethod
    @calibration
    def from_calibration(cal: dict):
        """Construct a Tank from a calibration dictionary.

        Parameters
        ----------
        cal: dict
            If empty, or if no `'channels'` entry is present, the values provided by
            `py::module::niess.bifrost.parameters::known_channel_params` are used.
            If 'channels' is present, it should contain a dictionary with per-channel
            parameters stored under a key 'channel_params', which is an integer keyed
            dictionary of variant-free parameters. The length of the channel_params
            dictionary should match the length of cal['channels']['angles'], a
            float-valued 1-D scipp.array of the channel angle relative to the tank
            centerline, defaulting to 9-channels at -40:10:40 degrees (inclusive)

        """
        from scipp import arange, linspace
        from .channel import Channel
        from .parameters import known_channel_params
        from niess.utilities import variant_parameters
        params = cal.get('channels', known_channel_params())
        variants = [{'variant': x} for x in ('s', 'm', 'l')]
        # The central a4 angle for each channel, relative to the reference tank angle
        angles = linspace('channel', -40, 40, 9, unit='degree', dtype='float')
        angles = params.get('angles', angles)
        # Assume the channel variants cycle through ('s', 'm', 'l') as in reality
        channel_params = {i: variants[i % 3] for i in range(angles.size)}
        # but this can be overridden by specifying an integer-keyed dictionary
        # with the parameters for each channel (and .pop removes it from params if present)
        channel_params = params.pop('channel_params', channel_params)

        # Which we might need to update with per-variant/constant parameters
        for val in channel_params.values():
            val.update(variant_parameters(val, params))

        channels = [Channel.from_calibration(angles[i], **channel_params[i]) for i in range(9)]
        return Tank(monitor=_elastic_monitor_from_params(cal),
                    channels=tuple(channels))

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
        return Tank(monitor=_elastic_monitor_from_params(params),
                    channels=tuple(channels))

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

    def to_mccode(
            self,
            assembler: Assembler,
            sample: Instance,
            settings: dict | None = None,
            flat: bool = True,
            **kwargs
    ):
        from ..mccode import add_niess_metadata, ensure_user_var, ensure_registry
        ensure_registry(assembler, "mcdotstar/mcstas-slit-radial@main") # for slits
        ensure_user_var(assembler, 'int', 'secondary_cassette', 'Secondary spectrometer analyzer cassette index')

        positions = self.slit_angles
        cov_x = self.slit_width

        slits_name = 'slits'
        declared_positions = f'{slits_name}_positions'
        assembler.declare_array('double', declared_positions, positions, source=__file__, line=173)
        slits = assembler.component(slits_name, 'Slit_radial_multi', at=((0, 0, 0,), sample))
        add_niess_metadata(slits, self, source_name=slits_name, role='physical-component')
        slits.set_parameters(slit_width=cov_x, offset='slitAngle*DEG2RAD',
                             number=len(positions), radius='slitDistance', height=0.2,
                             positions=declared_positions)
        # `slit` is >=0 iff scattered.
        # This could be `secondary_cassette = 1 + slit;` unambiguously
        slits.EXTEND("secondary_cassette = (SCATTERED) ? 1 + slit : -1;")

        # Insert the Bragg Peak elastic monitor -- it is outside the slits.
        # Rotated relative to `sample` as well as positioned there: `sample` is the
        # tank's rotating reference frame (sharing the sample's origin), and the
        # monitor turns with the tank. Left to default, the rotation would be
        # ABSOLUTE and the monitor would stay put as the tank rotated around it.
        mon = self.monitor.to_mccode(assembler, at=sample, rotate=sample)
        # The slit for this monitor was added last, so it _is_ the last one
        mon.WHEN(f"secondary_cassette == {len(positions)}")

        for index, channel in enumerate(self.channels):
            name = f"channel_{1 + index}"
            when = f"{1 + index} == secondary_cassette"
            channel.to_mccode(assembler, sample, name=name, when=when, settings=settings, flat=flat, **kwargs)

    def add_to_graph(self, upstream: str | None, name: str, graph: DiGraph):
        graph.add_node('slits')
        if upstream is not None:
            graph.add_edge(upstream, 'slits')
        cs = [channel.add_to_graph('slits', f"channel_{1 + index}", graph) for index, channel in enumerate(self.channels)]
        mn = self.monitor.add_to_graph(upstream, self.monitor.name, graph)
        return [*cs, mn]

    def efu_calibration(self):
        """Build the serializable representation of the EFU calibration data needed
        to correctly pixelate data produced by the triplets given their current
        calibrated resistances and resistivities"""
        import datetime
        cals = [x for z in [c.efu_calibration(i) for i, c in enumerate(self.channels)] for x in z]
        payload = {
            'version': 0,
            'date': datetime.datetime.now().isoformat(),
            'info': "Produced for BIFROST by niess",
            'instrument': 'bifrost',
            'groups': len(cals),
            'groupsize': 3,
            'Parameters': [c.to_dict() for c in sorted(cals, key=lambda x: x.group)]
        }
        return {'Calibration': payload}
