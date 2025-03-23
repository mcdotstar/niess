from dataclasses import dataclass


def variant_parameters(params: dict, default: dict):
    variant = params.get('variant', default['variant'])
    complete = {k: params.get(k, v[variant] if isinstance(v, dict) else v) for k, v in default.items()}
    return complete


@dataclass
class Channel:
    from mccode_antlr.assembler import Assembler
    from mccode_antlr.instr import Instance
    from scipp import Variable
    from .arm import Arm

    pairs: tuple[Arm, Arm, Arm, Arm, Arm]

    @staticmethod
    def from_calibration(relative_angle: Variable, **params):
        from math import pi
        from scipp import sqrt, tan, atan, asin, min, vector
        from scipp.constants import hbar, neutron_mass
        from scipp.spatial import rotations_from_rotvecs
        from .parameters import known_channel_params, tube_xz_displacement_to_quaternion
        from .arm import Arm

        vp = variant_parameters(params, known_channel_params())

        tau = params.get('tau', 2 * pi / vp['d_spacing'])

        sample = vp['sample']

        analyzer_vector = vector([1, 0, 0]) * vp['sample_analyzer_distance']

        ks = (sqrt(vp['energy'] * 2 * neutron_mass) / hbar).to(unit='1/angstrom')
        two_thetas = -2 * asin(0.5 * tau / ks)
        two_theta_vectors = two_thetas * vector([0, -1, 0])
        two_theta_rotation = rotations_from_rotvecs(two_theta_vectors)

        # Detector offsets are specified in a frame with x along the scattered beam, y in the plane of the analyzer
        add = 'analyzer_detector_distance'
        detector_vector = vector([1, 0, 0]) * vp[add] + vp['detector_offset'].to(unit=vp[add].unit)

        # Rotation of the whole analyzer channel around the vertical sample-table axis
        relative_rotation = rotations_from_rotvecs(relative_angle * vector([0, 0, 1]))

        analyzer_position = sample + relative_rotation * analyzer_vector
        detector_position = sample + relative_rotation * (analyzer_vector + two_theta_rotation * detector_vector)

        tau_vecs = relative_rotation * rotations_from_rotvecs(0.5 * two_theta_vectors) * (tau * vector([0, 0, -1]))

        # The detector orientation is given by a displacement vector of the tube-end, we want the associated quaternion
        detector_orient = tube_xz_displacement_to_quaternion(vp['detector_length'], vp['detector_orient'])

        # The detector tube orientation rotation(s) must be modified by the channel rotation:
        detector_orient = relative_rotation * detector_orient

        # vp['coverage'] is specified at 2.7 meV as +/- 2 degrees
        # and higher energies keep constant delta-Q-out-of-plane
        # this coverage is still only half, since both +/- directions have same Q extent
        coverages = atan(min(ks) * tan(1.0 * vp['coverage']) / ks)

        # print(f"Vertical coverage = {2*coverages.to(unit='degree'):c}")
        mosaic = vp['crystal_mosaic']

        resistance = vp['resistance']
        resistivity = vp['resistivity']
        from ..utilities import is_scalar
        from scipp import concat
        if is_scalar(resistance):
            contact_resistance = vp['contact_resistance']
            resistance = concat((contact_resistance, resistance, resistance, contact_resistance), dim='tube')
        if is_scalar(resistivity):
            resistivity = concat((resistivity, resistivity, resistivity), dim='tube')

        def idx_or(obj, index):
            return obj['analyzer', index] if 'analyzer' in obj.dims else obj

        pairs = []
        for idx, (ap, tv, dl, ct, cs, cc, gp) in enumerate(zip(
                analyzer_position, tau_vecs, vp['detector_length'], vp['blade_count'], vp['crystal_shape'], coverages,
                vp['gap']
        )):
            params = dict(
                sample=sample,
                blade_count=ct,
                shape=cs,
                mosaic=idx_or(mosaic, idx),
                analyzer_orient=relative_rotation,
                coverage=cc,
                detector_orient=idx_or(detector_orient, idx),
                resistance=idx_or(resistance, idx),
                resistivity=idx_or(resistivity, idx),
                gap=gp
            )
            pairs.append(Arm.from_calibration(ap, tv, detector_position['analyzer', idx], dl, **params))

        return Channel((pairs[0], pairs[1], pairs[2], pairs[3], pairs[4]))

    def triangulate_detectors(self, unit=None):
        from ..spatial import combine_triangulations
        return combine_triangulations([arm.triangulate_detector(unit=unit) for arm in self.pairs])

    def triangulate_analyzers(self, unit=None):
        from ..spatial import combine_triangulations
        return combine_triangulations([arm.triangulate_analyzer(unit=unit) for arm in self.pairs])

    def triangulate(self, unit=None):
        from ..spatial import combine_triangulations
        return combine_triangulations([arm.triangulate(unit=unit) for arm in self.pairs])

    def mcstas_parameters(self, sample: Variable):
        from .combine import combine_parameters
        return combine_parameters(self.pairs, sample)

    def sample_space_angle(self, sample: Variable):
        return self.pairs[0].sample_space_angle(sample)

    def coverage(self, sample: Variable, unit=None):
        from scipp import concat, max
        unit = unit or 'radian'
        cov_xy = [x.coverage(sample, unit=unit) for x in self.pairs]
        cov_x = max(concat([x for x, _ in cov_xy], dim='pairs'))
        cov_y = max(concat([y for _, y in cov_xy], dim='pairs'))
        return cov_x, cov_y

    def rtp_parameters(self, sample: Variable):
        from scipp import concat, all, isclose
        sa, ad, x, y, angle = zip(*[p.rtp_parameters(sample) for p in self.pairs])
        sa = concat(sa, dim='pairs')
        ad = concat(ad, dim='pairs')
        x7, y7, a7 = [concat(q[:2], dim='pairs') for q in (x, y, angle)]
        x9, y9, a9 = [concat(q[2:], dim='pairs') for q in (x, y, angle)]

        relative_angles = [arm.sample_space_angle(sample) for arm in self.pairs]
        ra0 = relative_angles[0]
        if not all(isclose(concat(relative_angles, dim='arm'), ra0)):
            raise RuntimeError("different relative angles for same-channel analyzers?!")

        return sa, ad, x7, y7, a7, x9, y9, a9, ra0

    def to_mccode(self, assembler: Assembler, relative: Instance, name: str, when: str = None, settings: dict = None, **kwargs):
        from scipp import concat, all, isclose, vector
        # For each channel we need to define the local coordinate system, relative to the provided sample
        origin = vector([0, 0, 0], unit='m')
        ra0 = self.sample_space_angle(origin).to(unit='degree').value
        cassette = assembler.component(f"{name}_arm", "Arm", at=((0, 0, 0), relative), rotate=((0, ra0, 0), relative))
        cassette.WHEN(when)

        for uv in ('int secondary_scattered;', 'int analyzer;', 'int flag;'):
            assembler.ensure_user_var(uv)

        for arm_index, arm in enumerate(self.pairs):
            arm_name = f"{name}_{1 + arm_index}"
            arm_when = f"0 == secondary_scattered && {when}"
            extend = f"secondary_scattered = (SCATTERED) ? 1 : 0;\nanalyzer = (SCATTERED) ? {1 + arm_index} : 0;"
            detector_when = f"{when} && {1 + arm_index}==analyzer"
            detector_extend = f"flag = (SCATTERED) ? 1 : 0;"
            arm.to_mccode(assembler, cassette, name=arm_name, analyzer_when=arm_when, analyzer_extend=extend,
                          settings=settings, detector_when=detector_when, detector_extend=detector_extend, **kwargs)
