"""BIFROST's own NeXus translators, from the tree.

Instrument-specific, and kept off the shared registry: `Triplet` and `Analyzer` are niess
classes another instrument could reuse, and importing the NeXus target must not give
another instrument's detectors BIFROST's pixel numbering. Ask for `BIFROST_REGISTRY`:

    from niess.nexus import to_nexus_structure
    from niess.nexus.bifrost import BIFROST_REGISTRY

    structure = to_nexus_structure(instrument, registry=BIFROST_REGISTRY)

Importing this module is what registers them, which is why the package `__init__` does
not do it for you.
"""
from __future__ import annotations

from ..walk import SKIP, Visit
from .nodes import attribute, dataset, group
from .registry import NEXUS_REGISTRY, NiessNexusRegistry
from .structure import component_body, emit


BIFROST_REGISTRY = NiessNexusRegistry(parent=NEXUS_REGISTRY)

def icd_pixel(resolution, arc, triplet, tube, position):
    """Pixel id per ICD 01 v6; ``position`` runs from 0 to ``resolution - 1``."""
    return 27 * resolution * arc + 9 * resolution * tube + resolution * triplet + position + 1

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
