"""The shape each component is drawn as.

One builder per component class, registered on `BREP_REGISTRY`, each taking a `Subject`
-- a name, the object if there is one, and the McCode parameters it reports. How that
subject was arrived at is not a builder's business: `niess.brep.assembly` walks the tree
for it. They are written against `__mccode__` parameters rather than against niess
fields because that is the description a component already publishes -- the fields it
does not publish, like `substrate`, are read off the object.
"""
from __future__ import annotations

from math import sqrt

from ..components.component import Component
from ..components.aperture import Jaw, Slit
from ..components.filter import Attenuator, NCrystalFilter, RadialFilterCollimator
from ..components.guide import EllipticGuide, StraightGuide, TaperedGuide
from ..components.source import ESSource
from .assembly import BREP_REGISTRY, Subject


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
        from loguru import logger
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
    return _box(float(width), float(height), _APERTURE_THICKNESS)

@BREP_REGISTRY.register(NCrystalFilter)
@BREP_REGISTRY.register(Attenuator)
def build_filter(subject):
    params = subject.params
    return _box(_param(params, 'xwidth'), _param(params, 'yheight'), _param(params, 'zdepth'))

@BREP_REGISTRY.register(ESSource)
def build_ess_source(subject):
    params = subject.params
    height = _param(params, 'yheight')
    width = params.get('focus_xw', height)
    length = params.get('dist', height)
    return _box(float(width), float(height), float(length))

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
        outer_shape = bd.Cylinder(outer, height, arc_size=angle)
        if inner > 0:
            outer_shape = outer_shape - bd.Cylinder(inner, height + _APERTURE_THICKNESS, arc_size=angle)
        shapes.append(outer_shape)

    if not shapes:
        return None
    return bd.Compound(shapes)

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
    return bd.Compound(children=[ez, ex, ey], label=subject.name)
