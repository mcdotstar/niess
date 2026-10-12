"""The shape each component is drawn as.

One builder per component class, registered on `BREP_REGISTRY`, each taking a `Subject`
-- a name, the object if there is one, and the McCode parameters it reports. How that
subject was arrived at is not a builder's business: `niess.brep.assembly` walks the tree
for it. They are written against `__mccode__` parameters rather than against niess
fields because that is the description a component already publishes -- the fields it
does not publish, like `substrate`, are read off the object.
"""
from __future__ import annotations

import logging
from math import sqrt

from ..components.component import Component
from ..components.aperture import Jaw, Slit
from ..components.chopper import DiscChopper, NXDiskChopper
from ..components.filter import Attenuator, NCrystalFilter, RadialFilterCollimator
from ..components.guide import EllipticGuide, StraightGuide, TaperedGuide
from ..components.moderator import ESSModerator
from .assembly import BREP_REGISTRY, Subject

logger = logging.getLogger(__name__)


_APERTURE_THICKNESS = 1e-4

def _bd():
    import build123d as bd
    return bd

def _param(params: dict[str, float], name: str, default: float | None = None):
    if name in params:
        return float(params[name])
    if default is not None:
        return default
    raise KeyError(name)

def _dimension(subject, name: str, default):
    """A value the object states, or the default when it states none.

    These are the things a McCode component does not publish -- how thick a guide's
    substrate is, how finely to approximate an ellipse -- so they are read off the niess
    object, which is the only thing that knows.
    """
    value = getattr(subject.obj, name, None)
    if value is None:
        return default
    return float(value.to(unit='m').value) if hasattr(value, 'to') else float(value)

SUBSTRATE = 0.01

RESOLUTION = 0.5

def _box(width: float, height: float, length: float):
    bd = _bd()
    return bd.Box(float(width), float(height), float(length))

def _shell_from_polygons(vertices, faces):
    bd = _bd()
    bd_faces = [
        bd.Face(
            bd.Wire.make_polygon([vertices[i] for i in face], close=True)
        ) for face in faces
    ]
    return bd.Shell(bd_faces)

def _solid_from_polygons(vertices, faces):
    bd = _bd()
    return bd.Solid(_shell_from_polygons(vertices, faces))

def _rectangular_prism(w1: float, h1: float, w2: float, h2: float, length: float):
    return _solid_from_polygons([
        [-w1, -h1, 0], [w1, -h1, 0], [w1, h1, 0], [-w1, h1, 0],
        [-w2, -h2, length], [w2, -h2, length], [w2, h2, length], [-w2, h2, length],
    ], [
        [0, 1, 2, 3], [1, 5, 6, 2], [2, 6, 7, 3], [3, 7, 4, 0], [0, 4, 5, 1],
        [7, 6, 5, 4]
    ]
    )

@BREP_REGISTRY.register(StraightGuide)
def build_straight_guide(subject):
    params = subject.params
    bd = _bd()
    substrate = _dimension(subject, 'substrate', SUBSTRATE)
    z = _param(params, 'l')
    w = _param(params, 'w1')/2
    h = _param(params, 'h1')/2
    inner = _rectangular_prism(w, h, w, h, z)
    w += substrate
    h += substrate
    outer = _rectangular_prism(w, h, w, h, z)

    guide = outer - inner
    guide.label = subject.name
    guide.color = bd.Color(0.5, 0, 0, alpha=0.5)
    return guide

@BREP_REGISTRY.register(TaperedGuide)
def build_tapered_guide(subject):
    params = subject.params
    bd = _bd()
    substrate = _dimension(subject, 'substrate', SUBSTRATE)
    z = _param(params, 'l')
    w1 = _param(params, 'w1')/2
    h1 = _param(params, 'h1')/2
    w2 = _param(params, 'w2')/2
    h2 = _param(params, 'h2')/2
    inner = _rectangular_prism(w1, h1, w2, h2, z)
    outer = _rectangular_prism(w1 + substrate, h1 + substrate, w2 + substrate, h2 + substrate, z)

    guide = outer - inner
    guide.label = subject.name
    guide.color = bd.Color(0.75, 0, 0, alpha=0.5)
    return guide

def _ellipse_parameters_from_widths(params: dict[str, float]):
    from numpy import sqrt

    def parameters(which, w, i, o, l):
        foci = i + l + o
        offset = foci / 2 - i
        if 'mid' in which:
            minor = w / 2
            major = sqrt(foci ** 2 + minor ** 2) / 2
        else:
            t, b = (o, i) if 'entrance' in which else (i, o)
            t += l
            w /= 2
            b = sqrt(b * b + w * w / 4) + sqrt(t * t + w * w / 4)
            major = b / 2
            minor = sqrt(b * b - foci * foci) / 2
        return major, minor, offset

    pars = dict(xw='xwidth', xi='linxw', xo='loutxw', yw='yheight', yi='linyh', yo='loutyh', l='l')
    p = {k: params[v] for k, v in pars.items()}

    dim_at = str(params['dimensionsAt'])
    major_x, minor_x, offset_x = parameters(dim_at, p['xw'], p['xi'], p['xo'], p['l'])
    major_y, minor_y, offset_y = parameters(dim_at, p['yw'], p['yi'], p['yo'], p['l'])

    return {
        'major_x': major_x, 'minor_x': minor_x, 'offset_x': offset_x,
        'major_y': major_y, 'minor_y': minor_y, 'offset_y': offset_y,
        'l': p['l'],
    }

def _elliptic_guide_ellipse_parameters(params: dict[str, float]):
    # Elliptic_guide_gravity uses a large number of parameters
    # If the following 6 are present we should use them preferentially
    bases = {'major': 'majorAxis', 'minor': 'minorAxis', 'offset': 'majorAxisoffset'}
    ext = {'x': 'xw', 'y': 'yh'}
    names = {f'{a}_{b}': f'{f}{s}' for a, f in bases.items() for b, s in ext.items()}
    pars = {k: params.get(v) for k, v in names.items()}

    if len(undef := [x for x in pars.values() if x is None]) == 0:
        pars['l'] = params.get('l')
    elif len(undef) < len(pars):
        msg = f'Only {len(pars)-len(undef)} of {len(pars)} best parameters are defined'
        logger.warning(f'Likely error state in Elliptic guide brep: {msg}')

    if len(undef):
        # But fall back to calculating axes and offsets from widths and lengths
        pars = _ellipse_parameters_from_widths(params)

    return pars

@BREP_REGISTRY.register(EllipticGuide)
def build_elliptic_guide(subject):
    params = subject.params
    from numpy import ceil, sqrt, arange
    bd = _bd()
    resolution = _dimension(subject, 'resolution', RESOLUTION)
    substrate = _dimension(subject, 'substrate', SUBSTRATE)

    p = _elliptic_guide_ellipse_parameters(params)

    # print(f'Elliptic guide {subject.name} parameters: {p}')

    def width_at(minor, major, at):
        return 0 if abs(at) > major else float(minor * sqrt(1 - (at/major)**2))

    count = int(ceil(p['l'] / resolution))
    rings = arange(count + 1) / count
    inner_vertices, outer_vertices = [], []
    for r in rings:
        z = float(r * p['l'])
        w = width_at(p['minor_x'], p['major_x'], -p['offset_x'] - p['minor_x'] + z)
        h = width_at(p['minor_y'], p['major_y'], -p['offset_y'] - p['minor_y'] + z)
        vs = [(-w, -h, z), (+w, -h, z), (+w, +h, z), (-w, +h, z)]
        inner_vertices.extend(vs)
        w += substrate
        h += substrate
        vs = [(-w, -h, z), (+w, -h, z), (+w, +h, z), (-w, +h, z)]
        outer_vertices.extend(vs)

    faces = [[0, 1, 2, 3]]
    for i in range(count):
        j0, j1, j2, j3, j4, j5, j6, j7 = [4 * i + k for k in range(8)]
        faces.extend([[j0, j1, j5, j4], [j1, j2, j6, j5], [j2, j3, j7, j6], [j3, j0, j4, j7]])
    n = len(inner_vertices)
    faces.append([n-1, n-2, n-3, n-4])

    outer = _solid_from_polygons(outer_vertices, faces)
    inner = _solid_from_polygons(inner_vertices, faces)

    x = outer - inner
    x.label = subject.name
    x.color = bd.Color('red', alpha=0.5)
    return x

@BREP_REGISTRY.register(Slit)
@BREP_REGISTRY.register(Jaw)
def build_aperture(subject):
    params = subject.params
    # the aperture's own dimensions, rather than the four edges it emits them as
    width = _dimension(subject, 'width', None)
    height = _dimension(subject, 'height', None)
    if width is None:
        if 'xwidth' in params:
            width = params['xwidth']
        else:
            width = params.get('xmax', 0.0) - params.get('xmin', 0.0)
    if height is None:
        if 'yheight' in params:
            height = params['yheight']
        else:
            height = params.get('ymax', 0.0) - params.get('ymin', 0.0)
    shape = _box(float(width), float(height), _APERTURE_THICKNESS)
    shape.color = _bd().Color('sienna')  # an absorber, boron-carbide brown
    return shape

@BREP_REGISTRY.register(NCrystalFilter)
@BREP_REGISTRY.register(Attenuator)
def build_filter(subject):
    params = subject.params
    shape = _box(_param(params, 'xwidth'), _param(params, 'yheight'), _param(params, 'zdepth'))
    shape.color = _bd().Color('mediumseagreen')
    return shape

# ESS_butterfly's outline, from McCode's share/ESS_butterfly-geometry.c: the moderator in
# the target's (z, x) plane, metres, closed (the last point is the first).
_BUTTERFLY_Z = (
    -0.19922764, -0.18484553, -0.20252845, -0.20795122, -0.21054471, -0.21030894,
    -0.20889431, -0.20535772, -0.20134959, -0.19639837, -0.19026829, -0.18390244,
    -0.17565041, -0.17093496, -0.14617886, -0.12873171, -0.092658537, -0.040552845,
    -0.017682927, -0.0091951221, -0.0023577231, 0.0051869889, 0.011788619, 0.017918699,
    0.023105689, 0.024991869, 0.024756099, 0.022162599, 0.018154469, 0.012731709,
    0.0056585389, -0.00023577214, 0.014146339, -0.029707317, 0.014146339,
    -0.00047154514, 0.015325199, 0.021691059, 0.024991869, 0.024991869, 0.022634149,
    0.018154469, 0.011552849, 0.0033008089, -0.0061300811, -0.0091951221, -0.060593496,
    -0.092658537, -0.17541463, -0.1850813, -0.19309756, -0.19899187, -0.20182114,
    -0.20582927, -0.20913008, -0.21078049, -0.21007317, -0.20630081, -0.20229268,
    -0.19828455, -0.18484553, -0.19922764, -0.15584553, -0.19922764,
)
_BUTTERFLY_X = (
    0.014279319, 3.1692034e-10, -0.017654432, -0.0259624, -0.034789615, -0.043876452,
    -0.051665172, -0.058934642, -0.064646372, -0.069059982, -0.072694722, -0.075031332,
    -0.076589082, -0.076589082, -0.076848702, -0.076589082, -0.076589082, -0.076589082,
    -0.076589082, -0.076848702, -0.075290962, -0.072694722, -0.068281112, -0.061790512,
    -0.053482542, -0.044136082, -0.033491495, -0.025443152, -0.019212176, -0.0129812,
    -0.0062309757, -0.00025962368, 0.014538943, 0.058415398, 0.10229185, 0.11709042,
    0.13266786, 0.14149508, 0.15213966, 0.16200537, 0.17135184, 0.17888093, 0.18589078,
    0.19082364, 0.19290063, 0.19341988, 0.19341988, 0.19341988, 0.19341988, 0.19186213,
    0.1882274, 0.18459266, 0.1806983, 0.17602507, 0.16849597, 0.15811101, 0.1492838,
    0.13993733, 0.13370636, 0.129812, 0.11709042, 0.10229185, 0.058415398, 0.014279319,
)
# ESS_butterfly's beamline angles and sector centres, from its DECLARE and INITIALIZE
_BUTTERFLY_BEAMLINES = {
    'N': (30.0, 36.0, 42.0, 48.0, 54.0, 60.0, 66.0, 72.0, 78.0, 84.0, 90.0),
    'E': (-30.0, -36.0, -42.0, -48.0, -54.0, -60.0, -66.0, -72.0, -78.0, -84.0, -90.0),
    'W': (150.0, 144.7, 138.0, 132.7, 126.0, 120.7, 114.0, 108.7, 102.0, 96.7, 90.0, 84.0),
    'S': (-150.0, -144.7, -138.0, -132.7, -126.0, -120.7, -114.0, -108.7, -102.0, -96.7,
          -90.0, -84.0),
}
_BUTTERFLY_CENTRES = {'N': (0.117, 0.0), 'W': (0.0, 0.0), 'S': (0.0, -0.185), 'E': (0.117, -0.185)}


def butterfly_outline(sector: str, beamline: int):
    """The moderator's outline in ESS_butterfly's own frame, as (x, z) pairs in metres.

    What its MCDISPLAY draws at the top and bottom of the moderator: the table, moved to
    the sector's centre and turned to the beamline's angle. Sector W beamline 11, the
    Test Beamline, is centred on its thermal face instead.
    """
    from math import cos, radians, sin
    sector = sector.strip().upper()[:1]
    angle = radians(_BUTTERFLY_BEAMLINES[sector][int(beamline) - 1])
    cx, cz = _BUTTERFLY_CENTRES[sector]
    if sector == 'W' and int(beamline) == 11:
        cx = 0.5 * 1.1 * 10.5e-2  # half the oversampled ThermalWidthSW[10]
    r11, r12, r21, r22 = cos(angle), -sin(angle), sin(angle), cos(angle)
    return [(r11 * (z - cz) + r12 * (x - cx), r21 * (z - cz) + r22 * (x - cx))
            for z, x in zip(_BUTTERFLY_Z, _BUTTERFLY_X)]


@BREP_REGISTRY.register(ESSModerator)
def build_ess_moderator(subject):
    """The butterfly's outline, as tall as the moderator -- not the monolith, target or
    beam ports, which its MCDISPLAY draws as well."""
    bd = _bd()
    obj = subject.obj
    height = float(obj.height.to(unit='m').value)
    outline = butterfly_outline(obj.sector, obj.beamline)[:-1]
    wire = bd.Wire.make_polygon([(x, -height / 2, z) for x, z in outline], close=True)
    shape = bd.extrude(bd.Face(wire), amount=height, dir=(0, 1, 0))
    shape.color = bd.Color('lightskyblue')
    return shape

# Neither chopper class says how thick its disc is; NXdisk_chopper's is infinitely thin.
DISC_THICKNESS = 0.01


@BREP_REGISTRY.register(NXDiskChopper)
@BREP_REGISTRY.register(DiscChopper)
def build_disc_chopper(subject):
    """The disc and its openings, about the spindle -- the chopper's position -- as
    NXdisk_chopper.comp draws it: each opening runs from its two edges' angles, measured
    from the zero mark, which sits ``zero_angle`` round from +y, and in from the rim to
    the inner radius that leaves ``height`` of opening either side of where the beam
    crosses. Angles turn counter-clockwise looking downstream, from +y towards +x. Drawn
    at the disc's reference orientation: its phase belongs to a time, not a drawing."""
    bd = _bd()
    obj = subject.obj
    radius = float(obj.radius.to(unit='m').value)
    crossing = float(sqrt(sum(v * v for v in obj.beam_offset().to(unit='m').value)))
    inner = crossing - float(obj.height.to(unit='m').value) / 2
    zero = float(obj.zero_angle.to(unit='deg').value)
    edges = [float(v) for v in obj.windows.to(unit='deg').values]
    on_axis = (bd.Align.NONE, bd.Align.NONE, bd.Align.CENTER)

    disc = bd.Cylinder(radius, DISC_THICKNESS)
    for start, stop in zip(edges[0::2], edges[1::2]):
        # build123d's arc turns from +x towards +y; these angles from +y towards +x
        cut = bd.Cylinder(2 * radius, 2 * DISC_THICKNESS, arc_size=stop - start, align=on_axis)
        if inner > 0:
            cut = cut - bd.Cylinder(inner, 3 * DISC_THICKNESS, align=on_axis)
        disc = disc - bd.Rot(0, 0, 90 - zero - stop) * cut
    disc.color = bd.Color('dimgray')
    return disc


@BREP_REGISTRY.register(RadialFilterCollimator)
def build_radial_filter_collimator(subject):
    params = subject.params
    bd = _bd()
    height = _param(params, 'yheight')
    angle = _param(params, 'angle_width')

    shapes = []
    for inner_key, outer_key in (
            ('filter_minimum_radius', 'filter_maximum_radius'),
            ('collimator_minimum_radius', 'collimator_maximum_radius'),
    ):
        inner = _param(params, inner_key)
        outer = _param(params, outer_key)
        if outer <= 0:
            continue
        # on its axis, centred in height: build123d's default centres the bounding box,
        # which slides a thin arc in onto the axis and halves its radii
        on_axis = (bd.Align.NONE, bd.Align.NONE, bd.Align.CENTER)
        outer_shape = bd.Cylinder(outer, height, arc_size=angle, align=on_axis)
        if inner > 0:
            outer_shape = outer_shape - bd.Cylinder(inner, height + _APERTURE_THICKNESS,
                                                    arc_size=angle, align=on_axis)
        shapes.append(outer_shape)

    if not shapes:
        return None
    # build123d's arc turns from +x about z; Radial_col_filter's is centred on the beam
    # (+z) about the vertical (y). Centre the arc on +x, stand the axis up, face the beam.
    turn = bd.Rot(0, -90, 0) * bd.Rot(-90, 0, 0) * bd.Rot(0, 0, -angle / 2)
    return bd.Compound([turn * shape for shape in shapes])

def _register_bifrost() -> None:
    """BIFROST's analyzers and triplets, drawn in the frames the tree places them in.

    Their blades and tubes are not drawn one by one: those carry positions measured from
    the sample in the calibration's frame, which composing onto their frames would place
    twice. The analyzer and the triplet describe them in their own frames instead, which
    is what the NeXus target writes too.
    """
    from ..bifrost.analyzer import Analyzer
    from ..bifrost.triplet import Triplet

    @BREP_REGISTRY.register(Analyzer)
    def build_analyzer(subject):
        """Each blade at its place on the Rowland circle, turned to focus, as the arm says."""
        import numpy as np
        from ..bifrost.arm import Arm
        bd = _bd()
        centres, normals, width, height, thickness = \
            subject.visit.ancestor(Arm).obj.local_blades()
        up = np.array([0., 1., 0.])
        blades = []
        for index, (centre, normal) in enumerate(zip(centres, normals)):
            along = np.cross(normal, up)
            plane = bd.Plane(origin=tuple(centre), x_dir=tuple(normal), z_dir=tuple(along))
            blade = bd.Location(plane) * _box(thickness, height, width)
            blade.label = f'blade_{index}'
            blades.append(blade)
        shape = bd.Compound(children=blades, label=subject.name)
        shape.color = bd.Color('steelblue')
        return shape

    @BREP_REGISTRY.register(Triplet)
    def build_triplet(subject):
        bd = _bd()
        offsets, length, radius = subject.obj.local_tubes()
        # build123d's cylinders run along z; these tubes run along y
        tubes = [bd.Pos(x, 0.0, 0.0) * bd.Rot(90, 0, 0) * bd.Cylinder(radius, length)
                 for x in offsets]
        for index, tube in enumerate(tubes):
            tube.label = f'tube_{index}'
        shape = bd.Compound(children=tubes, label=subject.name)
        shape.color = bd.Color('goldenrod')
        return shape


_register_bifrost()


@BREP_REGISTRY.register(Component)
def build_arm(subject):
    """Three short axes, for a named position with no shape of its own.

    Only for a bare Component. Resolving against an object walks up to the nearest
    registered base, so without this every window and every monitor -- none of which has
    a builder of its own -- would be drawn as a set of axes, and a CAD export would
    acquire thirty crosses nobody put there. Resolving against an emitted instance
    matches the class exactly and never had the question.
    """
    from ..components.component import Component
    if subject.obj is not None and type(subject.obj) is not Component:
        return None
    params = subject.params
    bd = _bd()
    width, length = 0.02, 0.2

    ez = bd.extrude(bd.Circle(width / 2), length)
    ex = bd.Plane(origin=(0,0,0), z_dir=(1,0,0)) * bd.extrude(bd.Circle(width / 2), length)
    ey = bd.Plane(origin=(0,0,0), z_dir=(0,1,0)) * bd.extrude(bd.Circle(width / 2), length)
    ex.label, ey.label, ez.label = 'x', 'y', 'z'
    return bd.Compound(children=[ez, ex, ey], label=subject.name)
