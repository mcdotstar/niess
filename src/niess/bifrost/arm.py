from dataclasses import dataclass

@dataclass
class Arm:
    from mccode_antlr.assembler import Assembler
    from mccode_antlr.instr import Instance
    from .analyzer import Analyzer
    from .triplet import Triplet
    from scipp import Variable

    analyzer: Analyzer
    detector: Triplet

    @staticmethod
    def from_calibration(a_position, tau, d_position, d_length, **params):
        from .analyzer import Analyzer
        from .triplet import Triplet

        analyzer_orient = params.get('analyzer_orient', None)
        detector_orient = params.get('detector_orient', None)
        # the analyzer focuses on the center tube of the triplet
        a_focus = d_position['tube', 1] if 'tube' in d_position.dims else d_position
        analyzer = Analyzer.from_calibration(a_position, a_focus, tau, **params, orient=analyzer_orient)
        detector = Triplet.from_calibration(d_position, d_length, **params, orient=detector_orient)
        return Arm(analyzer, detector)

    def triangulate_detector(self, unit=None):
        return self.detector.triangulate(unit=unit)

    def triangulate_analyzer(self, unit=None):
        return self.analyzer.triangulate(unit=unit)

    def triangulate(self, unit=None):
        from ..spatial import combine_triangulations
        return combine_triangulations([self.triangulate_analyzer(unit=unit), self.triangulate_detector(unit=unit)])

    def mcstas_parameters(self, sample: Variable):
        from numpy import stack, hstack
        from scipp import sqrt, dot, cross, vector, acos
        from ..spatial import is_scipp_vector, perpendicular_directions
        is_scipp_vector(sample, 'sample')

        # TODO find sample-analyzer and analyzer-detector distances, move positions into appropriate frames
        # analyzer_position -> [0, 0, sample-analyzer-distance]
        # detector_position -> [[dx0, dy0, dz0], [dx1, dy1, analyzer-detector-distance], [dx2, dy2, dz2]]
        # end_position -> z along analyzer-detector vector 'Arm' (in McStas local coordinate frame)

        sa = self.analyzer.central_blade.position - sample
        ad = (self.detector.tubes[1].at + self.detector.tubes[1].to)/2 - self.analyzer.central_blade.position
        distances = [sqrt(dot(x, x)).to(unit='m').value for x in (sa, ad)]
        # the coordinate system here has 'local' x along the beam, and z vertical
        # the McStas local cooridnate system always has z along the beam and y defines the local scattering plane normal
        # for BIFROST's analyzers, the two coordinate systems have parallel (or maybe antiparallel) y directions

        za = sa / sqrt(dot(sa, sa))
        zd = ad / sqrt(dot(ad, ad))
        yd = cross(za, zd)
        yd /= sqrt(dot(yd, yd))
        xd = cross(yd, zd)

        two_theta = acos(dot(za, zd))

        tube_com = self.detector.tube_com() - self.analyzer.central_blade.position
        tube_end = self.detector.tube_end()

        x, y, z = [vector(q) for q in [[1, 0, 0], [0, 1, 0], [0, 0, 1]]]

        # this could be simplified if we built the column matrix (xd, yd, zd)
        tube_com_x, tube_com_y, tube_com_z = [dot(tube_com, d) * i for d, i in zip((xd, yd, zd), (x, y, z))]
        tube_com_d = tube_com_x + tube_com_y + tube_com_z
        tube_end_x, tube_end_y, tube_end_z = [dot(tube_end, d) * i for d, i in zip((xd, yd, zd), (x, y, z))]
        tube_end_d = tube_end_x + tube_end_y + tube_end_z
        # shift the COM relative to the expected detector position
        tube_com_d.fields.z -= sqrt(dot(ad, ad))

        # this is not good. Can we verify which axis is the coordinate axis and which is the tube axis?
        d = stack((tube_com_d.to(unit='m').values, tube_end_d.to(unit='m').values), axis=1)

        hc, vc = self.analyzer.coverage(sample)
        a = hstack((self.analyzer.count, self.analyzer.central_blade.shape.to(unit='m').value, [hc.value, vc.value]))

        return {'distances': distances, 'analyzer': a, 'detector': d, 'two_theta': two_theta.value}

    def rtp_parameters(self, sample: Variable):
        from scipp import concat, cross, dot, sqrt
        sa = self.analyzer.central_blade.position - sample
        ad = (self.detector.tubes[1].at + self.detector.tubes[1].to)/2 - self.analyzer.central_blade.position

        out_of_plane = cross(ad, sa)
        x, y, angle = self.analyzer.rtp_parameters(sample, out_of_plane)
        return sqrt(dot(sa, sa)), sqrt(dot(ad, ad)), x, y, angle

    def sample_space_angle(self, sample: Variable):
        return self.analyzer.sample_space_angle(sample)

    def coverage(self, sample: Variable, unit=None):
        # The arm coverage is defined vertically by the analyzer, but the mean
        # horizontal divergence is defined by the active *detector* length
        unit = unit or 'radian'
        ana_hor, ana_ver = self.analyzer.coverage(sample, unit=unit)
        det_hor = self.detector.horizontal_coverage(sample, self.analyzer.central_blade.position, unit=unit)
        if det_hor > ana_hor:
            print(f'Detector under-illuminated: the detector width {det_hor} should be less than the analyzer width {ana_hor}')
        return det_hor, ana_ver

    def to_mccode(self, assembler: Assembler, ref: Instance, name: str,
                  analyzer_when: str = None, analyzer_extend: str = None,
                  detector_when: str = None, detector_extend: str = None, **kwargs):
        from scipp import concat, all, isclose, vector, dot, sqrt, atan2
        # For each channel we need to define the local coordinate system, relative to the provided sample
        origin = vector([0, 0, 0], unit='m')

        sa_vec = self.analyzer.central_blade.position
        ad_vec = (self.detector.tubes[1].at + self.detector.tubes[1].to) / 2 - sa_vec

        sample_analyzer_d = sqrt(dot(sa_vec, sa_vec)).to(unit='m')
        analyzer_detector_distance = sqrt(dot(ad_vec, ad_vec)).to(unit='m')

        x = dot(ad_vec, sa_vec / sample_analyzer_d)
        y = dot(ad_vec, vector([0, 0, 1]))
        two_theta = atan2(y=y, x=x).to(unit='degree').value
        theta = two_theta / 2

        point = f'{name}_analyzer_point'    # component name of the location of the analyzer
        mono = f'{name}_monochromator'      # component name of the analyzer itself
        orient = f'{name}_detector_angle'   # component name of the oriented arm pointing at the detector
        triplet = f'{name}_triplet'         # component name of the detector itself

        # Move to the center of the analyzer & reorient for monochromator scattering in vertical plane
        arm = assembler.component(point, "Arm", at=((0, 0, sample_analyzer_d.value), ref), rotate=((0, 0, 90), ref))
        if analyzer_when is not None:
            arm.WHEN(analyzer_when)
        # Insert the analyzer rotated by theta (origin is used for calculating coverage angles)
        self.analyzer.to_mccode(assembler, source=ref.name, relative=point, sink=triplet, theta=theta, name=mono,
                                when=analyzer_when, extend=analyzer_extend, origin=origin)
        # Change the coordinate system by theta -- total scattering angle is then 2theta
        det_angle = assembler.component(orient, "Arm", at=((0, 0, 0), mono), rotate=((0, theta, 0), mono))
        det_angle.WHEN(detector_when)
        # Insert the detector distance along that arm
        self.detector.to_mccode(assembler, relative=orient, distance=analyzer_detector_distance.value, name=triplet,
                                when=detector_when, extend=detector_extend,
                                component=kwargs.get('detector_component', None),
                                parameters=kwargs.get('detector_parameters', None))
