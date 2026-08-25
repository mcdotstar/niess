from __future__ import annotations

from math import sqrt

from niess.components.component import Component
from niess.components.aperture import Jaw, Slit
from niess.components.filter import Attenuator, NCrystalFilter, RadialFilterCollimator
from niess.components.guide import EllipticGuide, StraightGuide, TaperedGuide
from niess.components.source import ESSource
from ..provenance import NiessProvenance
from .registry import DEFAULT_BREP_REGISTRY

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


def _provenance_value(
        provenance: NiessProvenance | None,
        key: str,
        default: float | None = None,
):
    if provenance is not None and key in provenance.extra:
        return float(provenance.extra[key])
    if default is not None:
        return default
    raise KeyError(key)


def _box(width: float, height: float, length: float):
    bd = _bd()
    return bd.Box(float(width), float(height), float(length))


def _loft_rectangles(in_width: float, in_height: float, out_width: float, out_height: float, length: float):
    bd = _bd()
    half = length / 2
    with bd.BuildPart() as build:
        with bd.BuildSketch(bd.Plane(origin=(0, 0, -half))):
            bd.Rectangle(in_width, in_height)
        with bd.BuildSketch(bd.Plane(origin=(0, 0, half))):
            bd.Rectangle(out_width, out_height)
        bd.loft()
    return build.part


def _loft_ellipses(in_width: float, in_height: float, out_width: float, out_height: float, length: float):
    bd = _bd()
    half = length / 2
    with bd.BuildPart() as build:
        with bd.BuildSketch(bd.Plane(origin=(0, 0, -half))):
            bd.Ellipse(in_width / 2, in_height / 2)
        with bd.BuildSketch(bd.Plane(origin=(0, 0, half))):
            bd.Ellipse(out_width / 2, out_height / 2)
        bd.loft()
    return build.part


def _ellipse_span(major: float, minor: float, offset: float, z: float):
    if major == 0:
        return 0.0
    reduced = 1.0 - ((offset + z) / major) ** 2
    return 2.0 * minor * sqrt(max(0.0, reduced))


class _SafeInstrumentDisplay:
    def __init__(self, instr):
        from mccode_antlr.display.component_display import ComponentDisplay

        self._instr = instr
        self._components = {}
        for instance in instr.components:
            try:
                component_display = ComponentDisplay(instance.type)
                if not component_display.is_empty():
                    self._components[instance.name] = component_display
            except Exception:
                continue



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


@DEFAULT_BREP_REGISTRY.register(StraightGuide)
def build_straight_guide(_provenance, _instance, params: dict[str, float]):
    bd = _bd()
    substrate = _provenance.extra.get('substrate', 0.01)
    z = _param(params, 'l')
    w = _param(params, 'w1')/2
    h = _param(params, 'h1')/2
    inner = _rectangular_prism(w, h, w, h, z)
    w += substrate
    h += substrate
    outer = _rectangular_prism(w, h, w, h, z)

    guide = outer - inner
    guide.label = _instance.name
    guide.color = bd.Color(0.5, 0, 0, alpha=0.5)
    return guide


@DEFAULT_BREP_REGISTRY.register(TaperedGuide)
def build_tapered_guide(_provenance, _instance, params: dict[str, float]):
    bd = _bd()
    substrate = _provenance.extra.get('substrate', 0.01)
    z = _param(params, 'l')
    w1 = _param(params, 'w1')/2
    h1 = _param(params, 'h1')/2
    w2 = _param(params, 'w2')/2
    h2 = _param(params, 'h2')/2
    inner = _rectangular_prism(w1, h1, w2, h2, z)
    outer = _rectangular_prism(w1 + substrate, h1 + substrate, w2 + substrate, h2 + substrate, z)

    guide = outer - inner
    guide.label = _instance.name
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


@DEFAULT_BREP_REGISTRY.register(EllipticGuide)
def build_elliptic_guide(_provenance, _instance, params: dict[str, float]):
    from numpy import ceil, sqrt, arange
    bd = _bd()
    resolution = _provenance.extra.get('resolution', 0.5)
    substrate = _provenance.extra.get('substrate', 0.01)

    p = _elliptic_guide_ellipse_parameters(params)

    # print(f'Elliptic guide {_instance.name} parameters: {p}')

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
    x.label = _instance.name
    x.color = bd.Color('red', alpha=0.5)
    return x


@DEFAULT_BREP_REGISTRY.register(Slit)
@DEFAULT_BREP_REGISTRY.register(Jaw)
def build_aperture(provenance: NiessProvenance | None, _instance, params: dict[str, float]):
    width = provenance and provenance.extra.get('width')
    height = provenance and provenance.extra.get('height')
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


@DEFAULT_BREP_REGISTRY.register(NCrystalFilter)
@DEFAULT_BREP_REGISTRY.register(Attenuator)
def build_filter(_provenance, _instance, params: dict[str, float]):
    return _box(_param(params, 'xwidth'), _param(params, 'yheight'), _param(params, 'zdepth'))


@DEFAULT_BREP_REGISTRY.register(ESSource)
def build_ess_source(_provenance, _instance, params: dict[str, float]):
    height = _param(params, 'yheight')
    width = params.get('focus_xw', height)
    length = params.get('dist', height)
    return _box(float(width), float(height), float(length))


@DEFAULT_BREP_REGISTRY.register(RadialFilterCollimator)
def build_radial_filter_collimator(_provenance, _instance, params: dict[str, float]):
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

@DEFAULT_BREP_REGISTRY.register(Component)
def build_arm(_provenance, _instance, params: dict[str, float]):
    bd = _bd()
    width, length = 0.02, 0.2

    ez = bd.extrude(bd.Circle(width / 2), length)
    ex = bd.Plane(origin=(0,0,0), z_dir=(1,0,0)) * bd.extrude(bd.Circle(width / 2), length)
    ey = bd.Plane(origin=(0,0,0), z_dir=(0,1,0)) * bd.extrude(bd.Circle(width / 2), length)
    return bd.Compound(children=[ez, ex, ey], label=_instance.name)


def instrument_to_assembly(instr, params: dict[str, float] | None = None, registry=None):
    from mccode_antlr.display.instrument_display import InstrumentDisplay
    from mccode_antlr.display.render.brep import instrument_to_assembly as upstream
    from .registry import NiessBRepRegistry

    instr_display = instr if isinstance(instr, InstrumentDisplay) else _SafeInstrumentDisplay(instr)
    active_registry = DEFAULT_BREP_REGISTRY if registry is None else registry
    if isinstance(active_registry, NiessBRepRegistry):
        active_registry = active_registry.to_brep_registry(instr_display._instr)
    return upstream(instr_display, params=params, registry=active_registry)


def save_step(assembly_or_instr, path, params: dict[str, float] | None = None, registry=None):
    from mccode_antlr.display.render.brep import save_step as upstream

    assembly = assembly_or_instr
    if hasattr(assembly_or_instr, 'components') or hasattr(assembly_or_instr, '_instr'):
        assembly = instrument_to_assembly(assembly_or_instr, params=params, registry=registry)
    return upstream(assembly, path)
