"""ESS NeXus Structure JSON, from the tree rather than from an emitted instrument.

`niess.nexus` converts an assembled McStas instrument. Everything it needs, it recovers:
the placement from `Instr.resolve_orientations`, the run-time values by constant-folding
DECLARE blocks, a detector's arc and triplet by matching a regex against a generated
`WHEN` clause. It works, and it costs a thousand lines of reading back what the tree
said in the first place.

This reads the tree. A component's position and orientation are on the component; a
frame is a declared node, so a `depends_on` chain is the chain of frames a thing hangs
from; and a detector's arc and triplet are `visit.ancestor(...).index`.

Translators are registered per niess class, or written on the class as ``__nexus_leaf__``
and friends -- both work, and which reads better depends on the target. NeXus is mostly a
table of per-type mappings, so registration suits it; McStas has scaffolding to place, so
methods suit that.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from ..dispatch import NiessRegistry
from ..nexus.nodes import add_child, attribute, dataset, group
from ..walk import SKIP, Context, Visit, walk

INSTRUMENT_PATH = '/entry/instrument'
DEFAULT_NXLOG_ROOT = '/entry/parameters'


class NiessNexusRegistry(NiessRegistry):
    """Translator lookup for the NeXus target.

    Created with ``hooks='nexus'``, so a class carrying ``__nexus_leaf__`` is its own
    translator. Registering wins, which is what an instrument-specific conversion needs
    -- BIFROST's detectors must not give another instrument's their pixel numbering
    merely because a module was imported.
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent, hooks='nexus')


NEXUS_REGISTRY = NiessNexusRegistry()


@dataclass
class NexusContext(Context):
    """The instrument group being filled, and where things have been put in it."""
    nxlog_root: str = DEFAULT_NXLOG_ROOT
    instrument_group: dict = None
    #: NeXus path emitted at each visit, so a depends_on can name it.
    paths: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.instrument_group is None:
            self.instrument_group = group(
                'instrument', nx_class='NXinstrument',
                children=[dataset('name', self.instrument.name)])

    def linked_log(self, name: str, parameter: str,
                   attrs: dict | None = None) -> dict:
        """A value a run sets, as an NXlog whose datasets link to an existing one.

        A chopper's speed is not a number an instrument has; it is a knob, and what the
        file should say is where to read it. `niess.nexus` decides this by folding a
        McCode expression and seeing whether an instrument parameter survives. Here the
        component names the knob it declared.

        This builds an ``NXlog`` group whose *datasets* are `link` modules pointing into
        an ``NXlog`` published elsewhere in the file -- deep links to the value and time
        of one that already exists, rather than a link to the group itself. That is what
        lets the group carry attributes of its own, which it must when it is part of an
        ``NXtransformations`` chain and needs a ``transformation_type`` and a ``vector``
        the original has no reason to have.

        Not to be confused with the filewriter's ``link`` module, which is what the
        datasets inside it are; :func:`niess.nexus.streams.link_specifier` writes those.

        .. note::

           This assumes there *is* an ``NXlog`` elsewhere to point at -- somewhere an
           f144 module is publishing the parameter. Where that is not true the group has
           to be written directly instead, carrying its own value and time rather than
           links to someone else's. Nothing in niess needs that yet, and when something
           does this is where the choice belongs.
        """
        from ..nexus.streams import linked_nxlog
        return linked_nxlog(name, f'{self.nxlog_root}/{parameter}', attrs=attrs)

    def stream_group(self, selection: dict, name: str = 'data') -> dict:
        """One monitor's or detector's data stream, as the instrument chose it."""
        from ..nexus.streams import stream_group_from_selection
        return stream_group_from_selection(name, selection)

    def depends_on(self, frame) -> str:
        """What a thing in ``frame`` hangs from, as a NeXus path.

        The chain is the chain of frames the tree declares. Nothing here reads an
        emitted instrument to work out what depends on what.
        """
        if frame is None:
            return '.'
        return self.paths.get(frame, '.')


def _transformations(visit: Visit, position, rotation_deg) -> list:
    """A component's placement, as an NXtransformations group and a depends_on.

    Emitted relative to whatever the thing hangs from, which is what the tree already
    says. `niess.nexus` reaches for absolute orientations and then subtracts an origin
    back out, because an emitted instrument gives it no frames to hang from.
    """
    from scipp import norm

    context = visit.context
    parent = context.depends_on(visit.frame)
    children = []
    previous = parent

    length = float(norm(position).to(unit='m').value)
    if length:
        direction = [float(v) for v in (position / norm(position)).value]
        children.append(dataset(
            'translation', length, dtype='double',
            attrs={'units': 'm', 'transformation_type': 'translation',
                   'vector': direction, 'depends_on': previous}))
        previous = f'{INSTRUMENT_PATH}/{visit.name}/transformations/translation'

    for axis, angle in zip(('x', 'y', 'z'), rotation_deg):
        if not angle:
            continue
        vector = [1.0 if axis == a else 0.0 for a in ('x', 'y', 'z')]
        children.append(dataset(
            f'rotation_{axis}', float(angle), dtype='double',
            attrs={'units': 'degrees', 'transformation_type': 'rotation',
                   'vector': vector, 'depends_on': previous}))
        previous = (f'{INSTRUMENT_PATH}/{visit.name}/transformations/'
                    f'rotation_{axis}')

    if not children:
        return [], parent
    return [group('transformations', nx_class='NXtransformations',
                  children=children)], previous


def component_body(nx_class: str, children=None, attrs=None, name=None,
                   position=None, rotation=None) -> dict:
    """What a translator returns: the class and contents of one component's group.

    ``position`` and ``rotation`` state where the thing sits in the frame it hangs from,
    for the composites that have no placement of their own -- an analyzer is at its
    frame's origin, turned by the Bragg angle; a detector is a distance along its.
    Anything with a position and an orientation of its own is placed by those.
    """
    return {'nx_class': nx_class, 'children': list(children or []),
            'attrs': dict(attrs or {}), 'name': name,
            'position': position, 'rotation': rotation}


def _placed(visit: Visit, body: dict) -> dict:
    """One component's group, with its placement attached."""
    from ..components.frame import Frame
    from ..spatial import mccode_ordered_angles

    from scipp import vector

    obj = visit.obj
    if body.get('position') is not None or body.get('rotation') is not None:
        position = body.get('position')
        position = vector([0., 0., 0.], unit='m') if position is None else position
        rotation = body.get('rotation')
        angles = (0.0, 0.0, 0.0) if rotation is None else rotation
    elif isinstance(obj, Frame):
        position, angles = obj.position, obj.angles()
    elif hasattr(obj, 'position'):
        position, angles = obj.position, mccode_ordered_angles(obj.orientation)
    else:
        # a composite with no placement of its own sits at its frame's origin
        position, angles = vector([0., 0., 0.], unit='m'), (0.0, 0.0, 0.0)

    name = body.get('name') or visit.name
    transformations, depends = _transformations(visit, position, angles)
    children = list(body['children']) + transformations
    if transformations:
        children.append(dataset('depends_on', depends))
    node = group(name, nx_class=body['nx_class'], children=children)
    for key, value in body['attrs'].items():
        node = add_child(node, attribute(key, value)) if False else node
    visit.context.paths[visit.id] = depends
    return node


def emit(visit: Visit, body: dict) -> None:
    """Put one component's group into the instrument."""
    context = visit.context
    add_child(context.instrument_group, _placed(visit, body))


def to_nexus_structure(instrument, registry=None, nxlog_root: str | None = None) -> dict:
    """Convert ``instrument`` to ESS NeXus Structure JSON."""
    context = NexusContext(
        instrument=instrument,
        nxlog_root=DEFAULT_NXLOG_ROOT if nxlog_root is None else nxlog_root)
    walk(instrument, NEXUS_REGISTRY if registry is None else registry, context=context)
    entry = group('entry', nx_class='NXentry',
                  children=[context.instrument_group])
    return {'children': [entry]}


def translator(*classes):
    """Register a function returning a component body for one or more niess classes."""
    def decorate(func):
        def run(visit: Visit):
            body = func(visit)
            if body is not None:
                emit(visit, body)
            return body

        holder = type(func.__name__, (), {'leaf': staticmethod(run),
                                          '__doc__': func.__doc__})
        for klass in classes:
            NEXUS_REGISTRY.register(klass)(holder)
        return func

    return decorate


def _import(dotted: str):
    from importlib import import_module
    module, _, name = dotted.rpartition('.')
    return getattr(import_module(module), name)


def _lazy(*dotted: str):
    return [_import(name) for name in dotted]


def _da00_config(source: str, bins: int) -> dict:
    """The da00 configuration for a monitor's histogram.

    mccode_to_kafka stays the source of truth for the schema; this only says what this
    monitor's histogram looks like.
    """
    from mccode_to_kafka.writer import da00_dataarray_config, da00_variable_config
    axes = {
        'signal': {'unit': 'counts', 'label': f'{source} counts', 'shape': [bins]},
        'errors': {'unit': 'counts', 'label': f'{source} count errors', 'shape': [bins]},
        't': {'unit': 'microsecond', 'label': 'time since reference',
              'shape': [bins + 1]},
    }
    configs = {name: da00_variable_config(**spec, name=name, axes=['t'],
                                          data_type='float64')
               for name, spec in axes.items()}
    return da00_dataarray_config(topic=None, source=source,
                                 variables=[configs['signal'], configs['errors']],
                                 constants=[configs['t']])


def register_defaults() -> None:
    """Attach the per-type translators. Called on import; separate so it reads as a list."""
    from ..components.aperture import Aperture
    from ..components.chopper import DiscChopper
    from ..components.component import Component
    from ..components.filter import Filter
    from ..components.frame import Frame
    from ..components.guide import Guide
    from ..components.monitors import FrameMonitor
    from ..components.source import Source

    @translator(Component)
    def marker(visit):
        """Anything with a place but nothing else to say: a sample position, a window."""
        return component_body('NXcoordinate_system')

    @translator(Frame)
    def frame(visit):
        """A declared coordinate frame is a place to hang things, and nothing else."""
        return component_body('NXcoordinate_system')

    @translator(Source)
    def source(visit):
        return component_body('NXmoderator')

    @translator(Filter)
    def filtered(visit):
        return component_body('NXfilter')

    @translator(Guide)
    def guide(visit):
        """m is the guide's own field, not a number recovered from a component call."""
        obj = visit.obj
        children = [dataset('description', f'{type(obj).__name__} guide')]
        for face in ('left', 'right', 'top', 'bottom'):
            value = getattr(obj, face, None)
            if isinstance(value, (int, float)):
                children.append(dataset(f'm_{face}', float(value)))
        # a guide built in segments carries a length per segment, not one number
        from scipp import sum as ssum
        from ..utilities import is_scalar
        length = obj.length if is_scalar(obj.length) else ssum(obj.length)
        children.append(dataset('length', float(length.to(unit='m').value),
                                attrs={'units': 'm'}))
        return component_body('NXguide', children)

    @translator(Aperture)
    def aperture(visit):
        """An opening. Where its edges are driven at run time, they are links."""
        obj, context = visit.obj, visit.context
        children = [
            dataset('x_gap', float(obj.width.to(unit='m').value), attrs={'units': 'm'}),
            dataset('y_gap', float(obj.height.to(unit='m').value), attrs={'units': 'm'}),
        ]
        edges = getattr(obj, 'edge_parameters', None)
        if edges is not None:
            children.extend(context.linked_log(edge, parameter, attrs={'units': 'm'})
                            for edge, parameter in edges().items())
        return component_body('NXaperture', children)

    @translator(FrameMonitor)
    def monitor(visit):
        """A monitor, and how its data reaches the file.

        The choice is the instrument's -- histograms or events -- and it is recorded on
        the monitor. Left unset, a frame monitor histograms, which is what these have
        always done.
        """
        obj, context = visit.obj, visit.context
        children = [dataset('description', visit.name)]
        selection = obj.stream
        if selection is None:
            selection = {'module': 'da00',
                         'topic': f'{context.instrument.name.lower()}_beam_monitor',
                         'source': visit.name,
                         'config': _da00_config(visit.name, obj.time_bins())}
        children.append(context.stream_group(selection))
        return component_body('NXmonitor', children)

    @translator(DiscChopper)
    def disc_chopper(visit):
        """One disc, however many McStas components it would take to simulate it.

        This is the case that drove the whole refactor. A disc whose openings are
        neither identical nor evenly spaced cannot be a single McStas DiskChopper, so
        it becomes one per opening -- and `niess.nexus` puts it back together by reading
        group tags out of METADATA those components carry, tags invented for this and
        then read by three targets. Here the disc is a disc: it never came apart.
        """
        obj = visit.obj
        context = visit.context
        edges = [angle for opening in obj.slits() for angle in opening]
        return component_body('NXdisk_chopper', [
            dataset('slits', len(obj.slits())),
            # what a run sets, so the file says where to read it rather than guessing
            context.linked_log('rotation_speed', obj.speed_parameter(),
                         attrs={'units': 'Hz'}),
            context.linked_log('delay', obj.delay_parameter(), attrs={'units': 's'}),
            dataset('slit_edges', edges, dtype='double', attrs={'units': 'degrees'}),
            dataset('top_dead_center',
                    float(obj.zero_angle.to(unit='deg').value),
                    attrs={'units': 'degrees'}),
            dataset('beam_position',
                    float(obj.beam_angle.to(unit='deg').value),
                    attrs={'units': 'degrees'}),
            dataset('radius', float(obj.radius.to(unit='m').value),
                    attrs={'units': 'm'}),
            dataset('slit_height', float(obj.height.to(unit='m').value),
                    attrs={'units': 'm'}),
        ])


register_defaults()


# -- BIFROST -------------------------------------------------------------------
#
# Instrument-specific, and kept off the shared registry: Detector_tubes is not a
# BIFROST-only component, and importing this module must not give another instrument's
# detectors BIFROST's pixel numbering. Ask for BIFROST_REGISTRY to get these.

BIFROST_DETECTOR_TOPIC = 'bifrost_detector'
BIFROST_REGISTRY = NiessNexusRegistry(parent=NEXUS_REGISTRY)


def icd_pixel(resolution, arc, triplet, tube, position):
    """Pixel id per ICD 01 v6; ``position`` runs from 0 to ``resolution - 1``."""
    return 27 * resolution * arc + 9 * resolution * tube + resolution * triplet + position + 1


def bifrost_detector_source(arc, triplet) -> str:
    return f'arc={arc};triplet={triplet}'


def arc_and_triplet(visit: Visit) -> tuple[int, int]:
    """Which arc and which triplet, from where the thing sits in the instrument.

    `niess.nexus` matches a regex against a generated ``WHEN`` clause for this, because
    an emitted McStas instrument is all it has. The tree knows: a triplet is the arm it
    belongs to, in the channel that arm belongs to.
    """
    from ..bifrost.arm import Arm
    from ..bifrost.channel import Channel
    arm, channel = visit.ancestor(Arm), visit.ancestor(Channel)
    return (0 if arm is None else arm.index, 0 if channel is None else channel.index)


def _arm():
    from ..bifrost.arm import Arm
    return Arm


def register_bifrost() -> None:
    """BIFROST's analyzers and detectors, read off the objects."""
    from ..bifrost.analyzer import Analyzer
    from ..bifrost.triplet import Triplet
    from ..components.filter import RadialFilterCollimator
    from ..nexus.nodes import group as nx_group
    from ..nexus.off import NXoff

    def register(klass, func):
        def run(visit):
            body = func(visit)
            if body is not None:
                emit(visit, body)
            return SKIP

        BIFROST_REGISTRY.register(klass)(
            type(func.__name__, (), {'enter': staticmethod(run),
                                     'leaf': staticmethod(run),
                                     '__doc__': func.__doc__}))

    def analyzer(visit):
        """A Rowland-geometry analyzer, as a segmented NXcrystal.

        The blade count, shape and mosaic are the analyzer's own fields. The other way
        round they are McStas component parameters -- NH, zwidth, yheight, mosaic --
        read back out of a component call.
        """
        obj = visit.obj
        blade = obj.central_blade
        perp_q, perp_plane, _ = blade.shape.to(unit='m').value
        mosaic = float(blade.mosaic.to(unit='arcminute').value)
        count = int(obj.count)

        half_width, half_height = float(perp_q) / 2, float(perp_plane) / 2
        vertices, faces = [], []
        for i in range(count):
            x0 = (i - count // 2) * (2 * half_width)
            vertices.extend([
                [0, -half_height, x0 - half_width], [0, -half_height, x0 + half_width],
                [0, half_height, x0 + half_width], [0, half_height, x0 - half_width],
            ])
            faces.append([4 * i, 4 * i + 1, 4 * i + 2, 4 * i + 3])

        return component_body('NXcrystal', [
            dataset('usage', 'Bragg'),
            dataset('d_spacing', float(obj.central_blade.plane_spacing.to(unit='angstrom').value),
                    attrs={'units': 'angstrom'}),
            dataset('segment_width', float(perp_q), attrs={'units': 'm'}),
            dataset('segment_height', float(perp_plane), attrs={'units': 'm'}),
            dataset('segment_columns', count),
            dataset('segment_rows', 1),
            dataset('mosaic_horizontal', mosaic, attrs={'units': 'arcminutes'}),
            dataset('mosaic_vertical', mosaic, attrs={'units': 'arcminutes'}),
            NXoff(vertices, faces).to_nexus('geometry'),
        ], name=visit.emit_name('monochromator'),
           rotation=(0.0, float(visit.ancestor(_arm()).obj.analyzer_theta.value), 0.0))

    def detector(visit):
        """A triplet of He3 tubes: one shared cylinder, repositioned per pixel."""
        import numpy as np
        from scipp import dot, sqrt, vector

        obj = visit.obj
        arc, triplet = arc_and_triplet(visit)
        tubes = obj.tubes
        ni = len(tubes)
        nj = int(tubes[0].elements)
        radius = float(sum(t.radius.to(unit='m').value for t in tubes) / ni)
        lengths = [sqrt(dot(t.to - t.at, t.to - t.at)).to(unit='m').value for t in tubes]
        height = float(sum(lengths) / ni)
        centres = [(t.to + t.at) / 2 for t in tubes]
        span = centres[-1] - centres[0]
        width = float(sqrt(dot(span, span)).to(unit='m').value) + 2 * radius

        half_i = (width - 2 * radius) / 2
        di = np.linspace(-half_i, half_i, ni)
        half_pixel = height / nj / 2
        dj = -np.linspace(-height / 2 + half_pixel, height / 2 - half_pixel, nj)
        grid_j, grid_i = np.meshgrid(dj, di)

        numbers = [[icd_pixel(nj, arc, triplet, tube, position)
                    for position in range(nj)] for tube in range(ni)]

        geometry = nx_group('geometry', 'NXcylindrical_geometry', children=[
            dataset('vertices', [[0.0, -half_pixel, 0.0], [radius, -half_pixel, 0.0],
                                 [0.0, half_pixel, 0.0]],
                    dtype='double', attrs={'units': 'm'}),
            dataset('cylinders', [[0, 1, 2]]),
        ])

        return component_body('NXdetector', [
            dataset('detector_number',
                    np.array(numbers).astype('int32').tolist(), dtype='int32'),
            dataset('x_pixel_offset', grid_i.tolist(), dtype='double',
                    attrs={'units': 'm'}),
            dataset('y_pixel_offset', grid_j.tolist(), dtype='double',
                    attrs={'units': 'm'}),
            dataset('x_pixel_size', 2 * radius, attrs={'units': 'm'}),
            dataset('y_pixel_size', height / nj, attrs={'units': 'm'}),
            dataset('diameter', 2 * radius, attrs={'units': 'm'}),
            dataset('type', f'{ni} He3 tubes in series'),
            geometry,
        ], name=visit.emit_name('triplet'),
           position=vector([0., 0., 1.]) * visit.ancestor(_arm()).obj.analyzer_detector_distance)

    def collimator(visit):
        obj = visit.obj
        return component_body('NXcollimator', [
            dataset('type', 'radial'),
            dataset('divergence_x',
                    float(obj.collimation_angle.to(unit='degree').value),
                    attrs={'units': 'degrees'}),
        ])

    register(Analyzer, analyzer)
    register(Triplet, detector)
    BIFROST_REGISTRY.register(RadialFilterCollimator)(
        type('collimator', (), {'leaf': staticmethod(
            lambda visit: emit(visit, collimator(visit)))}))


register_bifrost()
