from __future__ import annotations

from niess.utilities import calibration
from niess.components import He3Monitor
from niess.components.component import Base

#: How much narrower than the channel spacing each radial slit is cut, as a fraction of
#: that spacing, so that neutrons on a boundary fall to one channel rather than to both.
SLIT_BOUNDARY_MARGIN = 1e-6


def _no_rotation():
    """No turn at all, as a fresh Variable every time; see :func:`_origin`."""
    from scipp import vector
    from scipp.spatial import rotations_from_rotvecs
    return rotations_from_rotvecs(vector([0., 0., 0.], unit='degree'))


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
    def channel_spacing(self) -> float:
        """The smallest angle between adjacent channels, in radians.

        The smallest rather than the nominal one: the nine channels are laid out on a
        uniform grid by default, but a calibration is free to supply its own angles and
        the slits must not overlap for any of them.
        """
        angles = sorted(self.channel_angles)
        if len(angles) < 2:
            raise ValueError(
                'a tank with fewer than two channels has no channel spacing; give the '
                'slits an explicit width instead'
            )
        return min(b - a for a, b in zip(angles, angles[1:]))

    @property
    def slit_radius(self):
        """How far from the sample the radial slits sit.

        The default for the drivable ``slitDistance``, not a fixed dimension: the slits
        exist to be scanned, and this is only where they start. 0.4 m is the value the
        instrument was previously compiled and run with.

        It clears everything further out, which is what it has to do: the radial
        collimators begin at 0.5 m, the elastic monitor is at 0.8 m and the nearest
        analyzer at 1.19 m.
        """
        from scipp import scalar
        return scalar(0.4, unit='m')

    @property
    def slit_width(self) -> float:
        """The angular width shared by every radial slit, in radians.

        The radial slits are not an aperture -- they are how a neutron leaving the
        sample gets tagged with the channel it entered. Slit_radial_multi accepts a
        neutron within ``slit_width/2`` of a slit angle and reports which one, and the
        emitted EXTEND turns that index into ``secondary_cassette``, which every
        channel's components are then gated on.

        So the only real constraints are that a slit be wide enough not to clip its
        channel's analyzer, and narrow enough not to reach its neighbour. The channel
        spacing gives both at once, and it is what the layout actually guarantees --
        where deriving the width from the analyzer's angular coverage did not: that
        route reached into every channel's blades to recover a number the geometry
        already fixes, and it went through the analyzer's *vertical* extent to get
        there, which only worked because doubling it happened to land below the
        spacing.

        The margin exists so a neutron arriving exactly on a boundary is not claimed by
        both neighbours. It only has to beat floating-point noise, so it is far too
        small to lose anything real -- at a 10-degree spacing it is a hundred-thousandth
        of a degree.
        """
        return self.channel_spacing * (1 - SLIT_BOUNDARY_MARGIN)

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

    def __mccode_enter__(self, visit):
        """Only the monitor's gate; the slits emit themselves.

        The elastic monitor has an opening of its own, added last, so the tag it waits
        for is the count of them.
        """
        # TODO after mccode-antlr is fully demoted, insert the tank in its own .instr
        # assembler = visit.context.assembler
        # visit.context.whens[f'{visit.id}/monitor'] = \
        #     f'secondary_cassette == {len(self.slit_angles)}'
        # return visit.context.push(assembler.included(f'{assembler.name}_tank'))
        visit.context.whens[f'{visit.id}/monitor'] = \
            f'secondary_cassette == {len(self.slit_angles)}'
        return None

    # TODO matching context-escape needed for eventual tank-section output
    # def __mccode_exit__(self, visit, entered):
    #     if entered is not None:
    #         visit.context.pop()

    def to_mccode(self, assembler: Assembler, sample: Instance, settings: dict | None = None, flat: bool = True, **kwargs):
        if flat:
            self.to_mccode_flat(assembler, sample, settings=settings, flat=flat, **kwargs)
        else:
            with assembler.included(f"{assembler.name}_tank") as section:
                self.to_mccode_flat(section, sample, settings=settings, flat=flat, **kwargs)

    def to_mccode_flat(
            self,
            assembler: Assembler,
            sample: Instance,
            settings: dict | None = None,
            flat: bool = True,
            **kwargs
    ):
        # The slits emit themselves, along with the run-time knobs, the array of
        # angles and the per-particle variable every channel below is gated on.
        self.slit_bank().to_mccode(assembler, at=sample, rotate=sample)

        # Insert the Bragg Peak elastic monitor -- it is outside the slits.
        # Rotated relative to `sample` as well as positioned there: `sample` is the
        # tank's rotating reference frame (sharing the sample's origin), and the
        # monitor turns with the tank. Left to default, the rotation would be
        # ABSOLUTE and the monitor would stay put as the tank rotated around it.
        mon = self.monitor.to_mccode(assembler, at=sample, rotate=sample)
        # The slit for this monitor was added last, so it _is_ the last one
        mon.WHEN(f"secondary_cassette == {len(self.slit_angles)}")

        for index, channel in enumerate(self.channels):
            name = f"channel_{1 + index}"
            when = f"{1 + index} == secondary_cassette"
            channel.to_mccode(assembler, sample, name=name, when=when, settings=settings, flat=flat, **kwargs)

    def slit_bank(self):
        """The radial slits, as the aperture they are.

        Derived rather than stored: every number in it comes from where the channels
        are, so a calibration that moves a channel moves the slit that tags it.
        """
        from scipp import array, scalar
        from ..components.slitbank import RadialSlitBank
        return RadialSlitBank(
            name='slits',
            stem='slit',   # the knobs are slitAngle and slitDistance
            position=_origin(),
            orientation=_no_rotation(),
            angles=array(values=self.slit_angles, dims=['slit'], unit='radian'),
            width=scalar(self.slit_width, unit='radian'),
            radius=self.slit_radius,
            height=scalar(0.2, unit='m'),
        )

    def __niess_children__(self):
        """The slits, then the monitor, then the channels -- which is emission order."""
        return (('slits', self.slit_bank()), ('monitor', self.monitor),
                *((f'channels[{i}]', c) for i, c in enumerate(self.channels)))

    def __niess_flow__(self, graph, path):
        """Ten paths leave the sample: nine channels and the elastic monitor.

        This is the case McCode cannot state. Its instrument is a list, so the only flow
        it can express is declaration order, and a neutron leaving the sample here takes
        exactly one of ten branches. NeXus can say it, through each group's `inputs` and
        `outputs`, which is why it is worth knowing.

        The radial slits are what choose, so they are where the branches start: the
        emitted component tags a neutron with a channel, or with the monitor's own
        opening, and everything downstream is gated on that tag.
        """
        (slit_label, slits), *rest = self.__niess_children__()
        entries, exits = slits.__niess_flow__(graph, path + (slit_label,))
        out: tuple[str, ...] = ()
        for label, child in rest:
            child_entries, child_exits = child.__niess_flow__(graph, path + (label,))
            for source in exits:
                for target in child_entries:
                    graph.add_edge(source, target)
            out = out + child_exits
        return entries, out


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
