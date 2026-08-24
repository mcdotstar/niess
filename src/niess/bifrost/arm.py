from __future__ import annotations

from niess.components.component import Base

class Arm(Base):
    from mccode_antlr.assembler import Assembler
    from mccode_antlr.instr import Instance
    from .analyzer import Analyzer
    from .triplet import Triplet
    from scipp import Variable

    analyzer: Analyzer
    detector: Triplet

    # -- geometry -------------------------------------------------------------
    # These describe where the analyzer and detector are relative to the sample. They
    # were computed inside to_mccode, which meant only the McStas conversion could see
    # them; they are properties of the arm, so they live on the arm.
    #
    # Note the sample is at the origin here. Arm.mcstas_parameters and
    # Arm.rtp_parameters take an explicit `sample` and subtract it, and they derive the
    # scattering angle a different way (acos of a dot product, unsigned, in radians).
    # Deliberately not unified: these are the quantities the emitted instrument is built
    # from, and this is a move, not a rewrite.

    @property
    def sample_analyzer_vector(self) -> Variable:
        """Sample to the centre of the analyzer."""
        return self.analyzer.central_blade.position

    @property
    def analyzer_detector_vector(self) -> Variable:
        """Analyzer centre to the middle of the central detector tube."""
        centre = (self.detector.tubes[1].at + self.detector.tubes[1].to) / 2
        return centre - self.sample_analyzer_vector

    @property
    def sample_analyzer_distance(self) -> Variable:
        from scipp import dot, sqrt
        vec = self.sample_analyzer_vector
        return sqrt(dot(vec, vec)).to(unit='m')

    @property
    def analyzer_detector_distance(self) -> Variable:
        from scipp import dot, sqrt
        vec = self.analyzer_detector_vector
        return sqrt(dot(vec, vec)).to(unit='m')

    @property
    def scattering_angle(self) -> Variable:
        """The total scattering angle, signed, in the arm's vertical plane.

        Measured from the incoming direction to the analyzer-detector direction, so it
        carries the sign that says which way the arm bends -- unlike the unsigned
        ``acos`` form in ``mcstas_parameters``.
        """
        from scipp import atan2, dot, vector
        sa_vec = self.sample_analyzer_vector
        ad_vec = self.analyzer_detector_vector
        x = dot(ad_vec, sa_vec / self.sample_analyzer_distance)
        y = dot(ad_vec, vector([0, 0, 1]))
        return atan2(y=y, x=x).to(unit='degree')

    @property
    def analyzer_theta(self) -> Variable:
        """Half the scattering angle: how far the analyzer is turned to reflect."""
        return self.scattering_angle / 2

    @classmethod
    def from_dict(cls, data):
        from .analyzer import Analyzer
        from .triplet import Triplet
        analyzer = data['analyzer']
        detector = data['detector']
        if not isinstance(analyzer, Analyzer):
            analyzer = Analyzer.from_dict(analyzer)
        if not isinstance(detector, Triplet):
            detector = Triplet.from_dict(detector)
        return cls(analyzer, detector)

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
        from scipp import vector
        from niess.mccode import add_niess_metadata
        # For each channel we need to define the local coordinate system, relative to the provided sample
        origin = vector([0, 0, 0], unit='m')

        sample_analyzer_d = self.sample_analyzer_distance
        analyzer_detector_distance = self.analyzer_detector_distance
        theta = self.analyzer_theta.value

        point = f'{name}_analyzer_point'    # component name of the location of the analyzer
        mono = f'{name}_monochromator'      # component name of the analyzer itself
        orient = f'{name}_detector_angle'   # component name of the oriented arm pointing at the detector
        triplet = f'{name}_triplet'         # component name of the detector itself

        # Move to the center of the analyzer & reorient for monochromator scattering in vertical plane
        arm = assembler.component(point, "Arm", at=((0, 0, sample_analyzer_d.value), ref), rotate=((0, 0, 90), ref))
        add_niess_metadata(arm, self, source_name=point, role='reference-frame',
                           extra={'frame': 'analyzer-point', 'arm': name})
        if analyzer_when is not None:
            arm.WHEN(analyzer_when)
        # Insert the analyzer rotated by theta (origin is used for calculating coverage angles)
        self.analyzer.to_mccode(assembler, source=ref.name, relative=point, sink=triplet, theta=theta, name=mono,
                                when=analyzer_when, extend=analyzer_extend, origin=origin)
        # Change the coordinate system by theta -- total scattering angle is then 2theta
        det_angle = assembler.component(orient, "Arm", at=((0, 0, 0), mono), rotate=((0, theta, 0), mono))
        add_niess_metadata(det_angle, self, source_name=orient, role='reference-frame',
                           extra={'frame': 'detector-angle', 'arm': name})
        det_angle.WHEN(detector_when)
        # Insert the detector distance along that arm
        self.detector.to_mccode(assembler, relative=orient, distance=analyzer_detector_distance.value, name=triplet,
                                when=detector_when, extend=detector_extend,
                                component=kwargs.get('detector_component', None),
                                parameters=kwargs.get('detector_parameters', None))


    def efu_calibration(self, group: int = -1):
        return self.detector.efu_calibration(group=group)