"""BIFROST-specific NeXus translators.

These live in niess rather than a downstream package because the components they
describe are niess's own: :mod:`niess.bifrost` builds the analyzers and detector
triplets these translate.

Ported from ``moreniius.additions``. Two things did not come along:

* ``readout_translator`` and the module-level ``BIFROST_DETECTOR_MODULES`` cache it
  read. The translator was never registered (its registration is commented out in
  ``additions.py``), so the cache was written on every detector translation and
  never read -- global mutable state with no consumer.
* ``detector_tubes_only_cylinder``, an unregistered alternative that gives every
  pixel its own cylinder. The registered variant shares one cylinder across pixels
  and positions it with per-pixel offsets.
"""
from __future__ import annotations

import logging
import re

from .instrument import component_body
from ..nodes import dataset, group
from ..off import NXoff
from .registry import DEFAULT_NEXUS_REGISTRY, NiessNexusRegistry
from ..streams import resolve_stream

logger = logging.getLogger(__name__)

BIFROST_DETECTOR_TOPIC = 'bifrost_detector'

#: The default translators plus the BIFROST-specific ones below. Pass it explicitly
#: to convert a BIFROST instrument::
#:
#:     from niess.nexus import to_nexus_structure
#:     from niess.nexus.bifrost import BIFROST_REGISTRY
#:     to_nexus_structure(instr, origin='sample_origin', registry=BIFROST_REGISTRY)
#:
#: Registering here rather than on DEFAULT_NEXUS_REGISTRY keeps the choice scoped to
#: the conversion that asks for it. Were these on the shared default, merely importing
#: this module would give any *other* instrument's Detector_tubes BIFROST's ICD pixel
#: numbering and detector topic -- and Detector_tubes is not a BIFROST-only component.
BIFROST_REGISTRY = NiessNexusRegistry(parent=DEFAULT_NEXUS_REGISTRY)

# BIFROST_nxs writes its triplet placement as "WHEN (c == secondary_cassette && a == analyzer)"
_WHEN_RE = re.compile(
    r'(?P<cassette>[0-9]+)\s*==\s*secondary_cassette\s*&&\s*(?P<analyzer>[0-9]+)\s*==\s*analyzer'
)


def icd_pixel(resolution, arc, triplet, tube, position):
    """Pixel id per ICD 01 v6; ``position`` runs from 0 to ``resolution - 1``."""
    return 27 * resolution * arc + 9 * resolution * tube + resolution * triplet + position + 1


def _arc_and_triplet(translation):
    """(arc, triplet) indices from the instance's WHEN clause, defaulting to (0, 0)."""
    match = _WHEN_RE.match(str(translation.instance.when))
    if match is None:
        return 0, 0
    # ICD indexing counts from zero; the WHEN clause counts from one
    return int(match.group('analyzer')) - 1, int(match.group('cassette')) - 1


def bifrost_detector_source(arc, triplet) -> str:
    return f'arc={arc};triplet={triplet}'


@BIFROST_REGISTRY.register_component_type('Monochromator_Rowland')
def monochromator_rowland_translator(t):
    """A Rowland-geometry analyzer, as a segmented NXcrystal."""
    half_height = t.parameter('yheight', dtype=float, default=0.0) / 2
    half_width = t.parameter('zwidth', dtype=float, default=0.0) / 2
    count = t.parameter('NH', dtype=int, default=1)
    gap = t.parameter('gap', dtype=float, default=0.0)

    mosaic = t.parameter('mosaic', dtype=float, default=0.0)
    mosaic_h = t.parameter('mosaich', dtype=float, default=0.0)
    mosaic_v = t.parameter('mosaicv', dtype=float, default=0.0)

    children = [
        dataset('usage', 'Bragg'),
        t.parameter_node('d_spacing', source='DM', dtype=float, attrs={'units': 'angstrom'}),
        dataset('segment_width', half_width * 2, attrs={'units': 'm'}),
        dataset('segment_height', half_height * 2, attrs={'units': 'm'}),
        dataset('segment_gap', gap, attrs={'units': 'm'}),
        dataset('segment_columns', count),
        # Monochromator_Rowland no longer defines NV; it is a single row of NH segments
        dataset('segment_rows', 1),
        dataset('mosaic_horizontal', mosaic_h or mosaic, attrs={'units': 'arcminutes'}),
        dataset('mosaic_vertical', mosaic_v or mosaic, attrs={'units': 'arcminutes'}),
    ]

    # nexus-constructor ignores the segment description when drawing, so give it an
    # explicit OFF surface. Without source and sink distances this cannot reproduce
    # the true Rowland curvature -- it is a flat approximation, not better data than
    # the McStas parameters above.
    vertices, faces = [], []
    for i in range(int(count)):
        x0 = (i - int(count) // 2) * (2 * half_width + gap)
        # An unrotated monochromator's crystal surface lies in the y-z plane
        vertices.extend([
            [0, -half_height, x0 - half_width],
            [0, -half_height, x0 + half_width],
            [0, half_height, x0 + half_width],
            [0, half_height, x0 - half_width],
        ])
        faces.append([4 * i, 4 * i + 1, 4 * i + 2, 4 * i + 3])
    children.append(NXoff(vertices, faces).to_nexus('geometry'))

    return component_body('NXcrystal', children)


@BIFROST_REGISTRY.register_component_type('Detector_tubes', 'Detector_time_tubes')
def detector_tubes_translator(t):
    """A triplet of He3 tubes: one shared cylinder, repositioned per pixel."""
    import numpy as np

    arc, triplet = _arc_and_triplet(t)

    # i is the slow direction (between tubes, McStas x); j is fast (along a tube, y)
    ni = t.parameter('N', dtype=int, default=1)
    nj = t.parameter('no', dtype=int, default=1)
    width = t.parameter('width', dtype=float, default=0.0)
    # `height` is the whole tube, and the whole tube is what gets binned:
    # Detector_tubes.comp assigns a bin with floor(no * ty) where ty is normalised
    # over lengths[i], which is `height` when `ends` is undefined. Its `dead_length`
    # parameter tapers detection probability towards the tube ends (p *= end_steps)
    # without narrowing the bin grid, so no active-length correction belongs here.
    height = t.parameter('height', dtype=float, default=0.0)
    radius = t.parameter('radius', dtype=float, default=0.0)

    half_i = (width - 2 * radius) / 2
    di = np.linspace(-half_i, half_i, ni)
    # nj bins of length height/nj tile the tube, so bin k is centred at
    # -height/2 + (k + 1/2) * height/nj -- matching floor(no * ty) exactly.
    # (height/(nj+1) would be counting the nj+1 bin *edges* as if they were pixels.)
    half_pixel = height / nj / 2
    # Signs verified against plots of the resulting detector positions
    dj = -np.linspace(-height / 2 + half_pixel, height / 2 - half_pixel, nj)
    grid_j, grid_i = np.meshgrid(dj, di)

    detector_number = [[icd_pixel(nj, arc, triplet, tube, position)
                        for position in range(nj)] for tube in range(ni)]

    in_series = t.parameter('wires_in_series', default=True)
    diameter = 2 * radius

    # One cylinder, defined by face centre, face edge, and opposite face centre;
    # the pixel offsets above place it repeatedly.
    geometry = group('geometry', 'NXcylindrical_geometry', children=[
        dataset('vertices',
                [[0.0, -half_pixel, 0.0], [radius, -half_pixel, 0.0], [0.0, half_pixel, 0.0]],
                dtype='double', attrs={'units': 'm'}),
        dataset('cylinders', [[0, 1, 2]]),
    ])

    # Event streaming is these tubes' established behaviour, so it is the default --
    # but an instrument that states a choice (a METADATA block, or a niess stream
    # selection recorded in provenance) overrides it.
    stream = resolve_stream(t, default={
        'module': 'ev44',
        'source': bifrost_detector_source(arc, triplet),
        'topic': BIFROST_DETECTOR_TOPIC,
    })

    children = [
        # int32 as the component intends: moreniius declared the same .astype('int32')
        # but its writer read the Python element type back off a .tolist() and widened
        # every integer array to int64.
        dataset('detector_number', np.array(detector_number).astype('int32').tolist(), dtype='int32'),
        dataset('x_pixel_offset', grid_i.tolist(), dtype='double', attrs={'units': 'm'}),
        dataset('y_pixel_offset', grid_j.tolist(), dtype='double', attrs={'units': 'm'}),
        dataset('x_pixel_size', diameter, attrs={'units': 'm'}),
        dataset('y_pixel_size', height / nj, attrs={'units': 'm'}),
        dataset('diameter', diameter, attrs={'units': 'm'}),
        dataset('type', f'{ni} He3 tubes in series' if in_series else f'{ni} He3 tubes'),
        geometry,
    ]
    if stream is not None:
        # Position matches moreniius, which inserted 'data' straight after detector_number
        children.insert(1, stream)

    return component_body('NXdetector', children)


# Frame_monitor is deliberately NOT registered here. niess.components.monitors
# emits it for every instrument, not just BIFROST, and its translation is the
# generic monitor one -- so it lives on DEFAULT_NEXUS_REGISTRY in translators.py.
# Registered here it would have stranded every other instrument's monitors as
# NXcoordinate_system, discarding the da00 stream their METADATA already carries.
