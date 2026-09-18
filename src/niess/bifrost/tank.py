from __future__ import annotations

from niess.utilities import calibration
from niess.components import He3Monitor
from niess.components.component import Base


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


def _filters_from_params(angles, params) -> tuple:
    from scipp import scalar, vector, collapse
    from scipp.spatial import rotations_from_rotvecs
    from ..components import RadialFilterCollimator

    mm = scalar(1., unit='mm', dtype='float')
    deg = scalar(1., unit='deg', dtype='float')
    kelvin = scalar(1., unit='K', dtype='float')

    def one_of(names, otherwise):
        for name in names:
            if name in params:
                return params[name]
        return otherwise

    fname, rname = 'beryllium_filter', 'radial_collimator'
    common = {
        'height': one_of([f'{x}_height' for x in (fname, rname)], 80 * mm),
        'angle_width': one_of([f'{x}_width' for x in (fname, rname)], 180 * deg),
        'temperature': one_of([f'{fname}_temperature'], 70 * kelvin),
        'composition': one_of([f'{fname}_ncrystal_cfg'], 'Be_sg194'),
    }
    for key, which in zip(('filter', 'collimator'), (fname, rname)):
        for radius in ('inner_radius', 'outer_radius'):
            common[f'{key}_{radius}'] = params.get(f'{which}_{radius}', 0 * mm)
    # collimation is the size of the entire wedge if not set
    common['collimation_angle'] = one_of([f'{rname}_collimation'], common['angle_width'])

    # the per-wedge orientation is its rotation about the vertical sample-table axis
    orientations = rotations_from_rotvecs(angles * vector([0, 1, 0]))

    return tuple(
        RadialFilterCollimator.from_calibration(
            {'name': f'wedge_{idx}', 'orientation': orientation} | common
        )
        for idx, orientation in enumerate(orientations)
    )


class Tank(Base):
    from scipp import Variable
    from .channel import Channel
    from ..components.filter import RadialFilterCollimator
    from mccode_antlr.assembler import Assembler
    from mccode_antlr.instr import Instance

    filters: tuple[RadialFilterCollimator, ...]
    monitor: He3Monitor
    channels: tuple[Channel, ...]

    @property
    def channel_angles(self) -> list[float]:
        """Where each channel sits about the sample, in radians."""
        return [c.sample_space_angle(_origin()).to(unit='radian').value
                for c in self.channels]

    @property
    def monitor_angle(self) -> float:
        """Where the elastic (Bragg peak) monitor sits, in radians.

        Outside the angles the wedges span, which is what lets it close their GROUP
        without competing with any of them for a neutron.
        """
        from scipp import atan2
        at = self.monitor.position - _origin().to(unit=self.monitor.position.unit)
        return atan2(y=at.fields.x, x=at.fields.z).to(unit='radian').value

    @property
    def channel_spacing(self) -> float:
        """The smallest angle between adjacent channels, in radians.

        The smallest rather than the nominal one: the nine channels are laid out on a
        uniform grid by default, but a calibration is free to supply its own angles and
        the wedges must not overlap for any of them.
        """
        angles = sorted(self.channel_angles)
        if len(angles) < 2:
            raise ValueError(
                'a tank with fewer than two channels has no channel spacing; give the '
                'wedges an explicit width instead'
            )
        return min(b - a for a, b in zip(angles, angles[1:]))

    @classmethod
    def from_dict(cls, data):
        from .channel import Channel
        from ..components.filter import RadialFilterCollimator as Filter
        cs = data['channels']
        if not hasattr(cs, '__len__'):
            raise ValueError('Channels must have length (probably 9)')
        cs = tuple(c if isinstance(c, Channel) else Channel.from_dict(c) for c in cs)
        mn = data['monitor']
        if not isinstance(mn, He3Monitor):
            mn = He3Monitor.from_dict(mn)
        fl = data['filters']
        if not hasattr(fl, '__len__') or len(fl) != len(cs):
            raise ValueError('Filters must have length equal to the number of channels')
        fl = tuple(f if isinstance(f, Filter) else Filter.from_dict(f) for f in fl)
        return cls(filters=fl, monitor=mn, channels=cs)

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
        from ..components.filter import RadialFilterCollimator as Filter
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
        return Tank(filters=_filters_from_params(angles, params),
                    monitor=_elastic_monitor_from_params(cal),
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
        return Tank(filters=_filters_from_params(angles[:3], params),
                    monitor=_elastic_monitor_from_params(params),
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
        """The cassette tag, written by whichever wedge a neutron scatters in.

        The wedges and the monitor share one GROUP, so a neutron takes exactly one of
        them; each EXTEND records which. The monitor goes last and so carries the
        index after the wedges', and closes the group.
        """
        # TODO after mccode-antlr is fully demoted, insert the tank in its own .instr
        # assembler = visit.context.assembler
        # return visit.context.push(assembler.included(f'{assembler.name}_tank'))

        for declaration in ('int secondary_cassette;',):
            visit.context.assembler.ensure_user_var(declaration)

        def extend(n: int):
            return f"""if (SCATTERED) secondary_cassette = {n + 1};"""

        for i, w in enumerate(self.filters):
            visit.context.extends[f'{visit.id}/filter[{i}]'] = extend(i)
            visit.context.groups[f'{visit.id}/filter[{i}]'] = 'filters_monitor'

        visit.context.extends[f'{visit.id}/monitor'] = extend(len(self.filters))
        visit.context.groups[f'{visit.id}/monitor'] = 'filters_monitor'
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
        uservar = "secondary_cassette"
        group = "filters_monitor"
        def set_channel(n: int):
            return f"""if (SCATTERED) {uservar} = {n + 1};"""

        def is_channel(n: int):
            return f'{n + 1} == {uservar}'

        assembler.ensure_user_var(f'int {uservar};')

        for index, wedge in enumerate(self.filters):
            obj = wedge.to_mccode(assembler, at=sample, rotate=sample, **kwargs)
            obj.EXTEND(set_channel(index))
            obj.GROUP(group)

        # Insert the Bragg Peak elastic monitor -- it is outside the slits.
        # Rotated relative to `sample` as well as positioned there: `sample` is the
        # tank's rotating reference frame (sharing the sample's origin), and the
        # monitor turns with the tank. Left to default, the rotation would be
        # ABSOLUTE and the monitor would stay put as the tank rotated around it.
        mon = self.monitor.to_mccode(assembler, at=sample, rotate=sample)
        mon.EXTEND(set_channel(len(self.filters)))
        mon.GROUP(group)

        for index, channel in enumerate(self.channels):
            name = f"channel_{1 + index}"
            channel.to_mccode(assembler, sample, name=name, when=is_channel(index), settings=settings, flat=flat, **kwargs)

    def __niess_children__(self):
        """The filters, then the monitor, then the channels -- i.e., emission order"""
        return (
            tuple((f'filter[{i}]', f) for i, f in enumerate(self.filters))
            +(('monitor', self.monitor),)
            + tuple((f'channels[{i}]', c) for i, c in enumerate(self.channels))
        )


    def __niess_flow__(self, graph, path):
        """Ten paths leave the sample: nine channels and the elastic monitor.

        This is the case McCode cannot state. Its instrument is a list, so the only flow
        it can express is declaration order, and a neutron leaving the sample here takes
        exactly one of ten branches. NeXus can say it, through each group's `inputs` and
        `outputs`, which is why it is worth knowing.
        """
        children = self.__niess_children__()
        filters = children[:len(self.filters)]
        monitor_label, monitor = children[len(filters)]
        channels = children[len(filters)+1:]

        # Every node has to be registered by the child that owns it: returning a path
        # the tank built itself leaves the node absent unless a parent happens to draw
        # an edge to it, which is why the tank alone used to graph as nine disconnected
        # channels with no monitor in them at all.
        monitor_entries, exits = monitor.__niess_flow__(graph, path + (monitor_label,))

        # Each filter-channel pair is (sample -- filter -- {channel})
        entries = monitor_entries
        for (wedge_label, wedge), (channel_label, channel) in zip(filters, channels):
            wedge_entries, wedge_exits = wedge.__niess_flow__(graph, path + (wedge_label,))
            channel_entries, channel_exits = channel.__niess_flow__(graph, path + (channel_label,))
            for source in wedge_exits:
                for target in channel_entries:
                    graph.add_edge(source, target)
            entries = entries + wedge_entries
            exits = exits + channel_exits

        return entries, exits

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
