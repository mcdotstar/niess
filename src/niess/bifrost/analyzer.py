from niess.components.component import Base
from typing import ClassVar, Type

class Analyzer(Base):
    from mccode_antlr.assembler import Assembler
    from ..components import Crystal
    from scipp import Variable

    blades: tuple[Crystal, ...]  # 7-9 blades

    __struct_field_types__: ClassVar[dict[str, Type]] = {'blades': tuple[Crystal, ...]}

    @classmethod
    def from_dict(cls, data):
        from ..components import Crystal
        blades = data['blades']
        if not hasattr(blades, '__len__') or (len(blades) != 7 and len(blades) != 9):
            raise ValueError('Blades must have 7 or 9 elements')
        blades = tuple(b if isinstance(b, Crystal) else Crystal.from_dict(b) for b in blades)
        return cls(blades)

    @property
    def central_blade(self):
        return self.blades[len(self.blades) >> 1]

    @property
    def count(self):
        return len(self.blades)

    @staticmethod
    def from_calibration(position: Variable, focus: Variable, tau: Variable, **params):
        from scipp import scalar, vector
        from scipp.spatial import rotation
        from ..spatial import is_scipp_vector
        from .rowland import rowland_blades
        from ..components import Crystal
        map(lambda x: is_scipp_vector(*x), ((position, 'position'), (focus, 'focus'), (tau, 'tau')))
        count = params.get('blade_count', scalar(9))  # most analyzers have 9 blades
        shape = params.get('shape', vector([10., 200., 2.], unit='mm'))
        orient = params.get('orient', None)
        orient = rotation(value=[0, 0, 0, 1.]) if orient is None else orient
        mosaic = params.get('mosaic', scalar(40., unit='arcminutes'))
        # qin_coverage = params.get('qin_coverage', params.get('coverage', scalar(0.1, unit='1/angstrom')))
        coverage = params.get('coverage', scalar(2.0, unit='degree'))
        source = params.get('source', params.get('sample_position', vector([0, 0, 0], unit='m')))
        gap = params.get('gap', None)
        #
        # Use the Rowland geometry to define each blade position & normal direction
        positions, taus = rowland_blades(source, position, focus, coverage, shape.fields.x, count.value, tau, gap)

        blades = [Crystal(p, t, shape, orient, mosaic) for p, t in zip(positions, taus)]
        return Analyzer(tuple(blades))

    def triangulate(self, unit=None):
        from ..spatial import combine_triangulations
        vts = [blade.triangulate(unit=unit) for blade in self.blades]
        return combine_triangulations(vts)

    def bounding_box(self, basis: Variable, unit=None):
        from scipp import concat
        from ..spatial import combine_bounding_boxes
        boxes = concat(tuple(b.bounding_box(basis, unit) for b in self.blades), dim='blades')
        return combine_bounding_boxes(boxes)

    def coverage(self, sample: Variable, unit=None):
        from scipp import norm, dot, cross, max, min, atan2, vector, concat
        unit = unit or 'radian'
        # Define a pseudo McStas coordinate system (requiring y is mostly vertical)
        z = (self.central_blade.position - sample)
        dist = norm(z)
        z = z / dist
        y = cross(cross(z, vector([0, 0, 1.0])), z)
        y = y / norm(y)
        x = cross(y, z)  # should have length 1 but normalized in bounding_box
        basis = concat((x, y), dim='basis')
        box = self.bounding_box(basis, unit=dist.unit)
        lengths = box['limits', 1] - box['limits', 0]
        return tuple(2 * atan2(y=e/2, x=dist).to(unit=unit) for e in lengths)

    def sample_space_angle(self, sample: Variable):
        from scipp import dot, atan2, vector
        z = (self.central_blade.position - sample)
        sample_space_x = vector([1, 0, 0])
        sample_space_y = vector([0, 1, 0])
        return atan2(y=dot(sample_space_y, z), x=dot(sample_space_x, z)).to(unit='radian')

    def rtp_parameters(self, sample: Variable, oop: Variable):
        from scipp import concat
        p0 = self.central_blade.position
        # exploit that for x in zip returns first all the first elements, then all the second elements, etc.
        x, y, a = [concat(x, dim='blades') for x in zip(*[b.rtp_parameters(sample, p0, oop) for b in self.blades])]
        return x, y, a

    def mcstas_parameters(self, sample: Variable, source: str, sink: str) -> dict:
        from mccode_antlr.instr import Instance
        from ..spatial import is_scipp_vector
        is_scipp_vector(sample, 'sample')
        source = source.name if isinstance(source, Instance) else source
        sink = sink.name if isinstance(sink, Instance) else sink
        if not isinstance(source, str) or not isinstance(sink, str):
            raise ValueError(f'The source and sink are expected to be str values not {type(source)} and {type(sink)}')

        perp_q, perp_plane, parallel_q = self.central_blade.shape.to(unit='m').value
        hor_cov, ver_cov = self.coverage(sample)
        params = dict(
            NH=self.count,
            zwidth=perp_q,
            yheight=perp_plane,
            mosaic=self.central_blade.mosaic.to(unit='arcminute').value,
            DM=3.355,
            gap=0.002,
            show_construction='showconstruction',
            angle_h=ver_cov.to(unit='degree').value,
            source=f'"{source}"',
            sink=f'"{sink}"'
        )
        return params

    def to_mccode(self, assembler: Assembler, source: str, relative: str, sink: str, theta: float, name: str,
                  when: str = None, extend: str = None, origin: Variable = None):
        mono = assembler.component(name, 'Monochromator_Rowland',
                                   at=((0, 0, 0), relative), rotate=((0, theta, 0), relative))
        mono.set_parameters(**self.mcstas_parameters(origin, source, sink))
        mono.WHEN(when)
        mono.EXTEND(extend)

