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
from ..walk import Context, Visit, walk

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


def component_body(nx_class: str, children=None, attrs=None, name=None) -> dict:
    """What a translator returns: the class and contents of one component's group."""
    return {'nx_class': nx_class, 'children': list(children or []),
            'attrs': dict(attrs or {}), 'name': name}


def _placed(visit: Visit, body: dict) -> dict:
    """One component's group, with its placement attached."""
    from ..components.frame import Frame
    from ..spatial import mccode_ordered_angles

    obj = visit.obj
    if isinstance(obj, Frame):
        position, angles = obj.position, obj.angles()
    else:
        position, angles = obj.position, mccode_ordered_angles(obj.orientation)

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
        children.append(dataset('length', float(obj.length.to(unit='m').value),
                                attrs={'units': 'm'}))
        return component_body('NXguide', children)

    @translator(Aperture)
    def aperture(visit):
        obj = visit.obj
        return component_body('NXaperture', [
            dataset('x_gap', float(obj.width.to(unit='m').value), attrs={'units': 'm'}),
            dataset('y_gap', float(obj.height.to(unit='m').value), attrs={'units': 'm'}),
        ])

    @translator(FrameMonitor)
    def monitor(visit):
        return component_body('NXmonitor', [dataset('description', visit.name)])

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
        edges = [angle for opening in obj.slits() for angle in opening]
        return component_body('NXdisk_chopper', [
            dataset('slits', len(obj.slits())),
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
