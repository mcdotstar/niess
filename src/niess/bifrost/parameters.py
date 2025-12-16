from scipp import Variable


def known_channel_params():
    from scipp import array, scalar, vector, vectors
    known = dict()
    dist_sa = {
        's': [1.100, 1.238, 1.342, 1.443, 1.557],
        'm': [1.189, 1.316, 1.420, 1.521, 1.623],
        'l': [1.276, 1.392, 1.497, 1.599, 1.701],
    }
    known['sample_analyzer_distance'] = {k: array(values=v, unit='m', dims=['analyzer']) for k, v in dist_sa.items()}
    known['analyzer_detector_distance'] = known['sample_analyzer_distance']['m']
    d_length_mm = {
        's': [217.9, 242.0, 260.8, 279.2, 298.8],
        'm': [226.0, 249.0, 267.9, 286.3, 304.8],
        'l': [233.9, 255.9, 274.9, 293.4, 311.9],
    }
    dex = scalar(10, unit='mm')  # The detector tubes were ordered with 10 mm extra length buffer
    known['detector_length'] = {k: dex + array(values=v, unit='mm', dims=['analyzer']) for k, v in d_length_mm.items()}
    known['detector_offset'] = vectors(values=[[0, 0, -14.], [0, 0, 0], [0, 0, 14]], unit='mm', dims=['tube'])
    known['detector_orient'] = vector([0, 0, 0], unit='mm')
    a_shape_mm = {
        's': [[12.0, 134, 1], [14.0, 147, 1], [11.5, 156, 1], [12.0, 165, 1], [13.5, 177, 1]],
        'm': [[12.5, 144, 1], [14.5, 156, 1], [11.5, 165, 1], [12.5, 174, 1], [13.5, 183, 1]],
        'l': [[13.5, 150, 1], [15.0, 162, 1], [12.0, 171, 1], [13.0, 180, 1], [14.0, 189, 1]],
    }
    known['crystal_shape'] = {k: vectors(values=v, unit='mm', dims=['analyzer']) for k, v in a_shape_mm.items()}
    known['crystal_mosaic'] = scalar(40., unit='arcminutes')
    known['blade_count'] = array(values=[7, 7, 9, 9, 9], dims=['analyzer'])  # two lowest energy analyzer have 7 blades
    known['d_spacing'] = scalar(3.355, unit='angstrom')  # PG(002)
    known['coverage'] = scalar(2., unit='degree') # +/- 2 degrees at 2.7 meV, constant delta-Q at higher energies
    known['energy'] = array(values=[2.7, 3.2, 3.8, 4.4, 5.], unit='meV', dims=['analyzer'])
    known['sample'] = vector([0, 0, 0.], unit='m')
    known['gap'] = array(values=[2, 2, 2, 2, 2.], unit='mm', dims=['analyzer'])
    known['variant'] = 'm'

    known['resistance'] = scalar(380., unit='Ohm')
    known['contact_resistance'] = scalar(88.0/2, unit='Ohm')
    known['resistivity'] = scalar(185., unit='Ohm/in').to(unit='Ohm/m')

    return known

def tank_parameters():
    from scipp import scalar
    known = dict()
    known['channels'] = known_channel_params()
    known['sample_elastic_monitor_distance'] = scalar(800., unit='mm')
    known['tank_elastic_monitor_angle'] = scalar(59., unit='deg')
    known['elastic_monitor'] = {
        'name': 'elastic_monitor',
        'radius': scalar(1., unit='inch').to(unit='mm'),
        'length': scalar(3.2, unit='inch').to(unit='mm'),
        'pressure': scalar(0.2, unit='atm'),
    }
    return known


def tube_xz_displacement_to_quaternion(length: Variable, displacement: Variable):
    from scipp import vector, scalar, any, sqrt, allclose
    from ..spatial import vector_to_vector_quaternion
    com_to_end = length * vector([0, 0.5, 0]) + displacement
    l2 = length * length
    x2 = displacement.fields.x * displacement.fields.x
    z2 = displacement.fields.z * displacement.fields.z

    com_to_end.fields.y = sqrt(0.25 * l2 - x2 - z2)

    y2 = displacement.fields.y * displacement.fields.y
    if any(y2 > scalar(0, unit=y2.unit)) and not allclose(com_to_end.fields.y, 0.5 * length - displacement.fields.y):
        raise RuntimeError("Provided tube-end displacement vector(s) contain wrong y-component value(s)")

    # The tube *should* point along y, but we were told it is displaced in x and z;
    # return the orienting Quaternion that takes (010) to the actual orientation
    quaternion = vector_to_vector_quaternion(vector([0, 1, 0]), com_to_end)
    return quaternion


def primary_parameters(use_tcs=False):
    from scipp import array, vector, scalar, norm
    from scipp.spatial import rotations_from_rotvecs as r
    from ..spatial import mccode_quaternion, at_relative_dict, at_relative
    from .guide_compressor import primary_compressor_parameters
    from .guide_curved import curved_guide_parameters
    from .guide_expanding import expanding_guide_parameters
    from .guide_straight import straight_guide_parameters
    from .guide_closing import closing_guide_parameters
    p = dict()

    m = scalar(1.0, unit='m')
    mm = scalar(1.0, unit='mm').to(unit='m')
    z = vector([0, 0, 1.0])

    eps = 1.0e-5
    # The guide is defined in the 'w4' coordinate system
    guide_zero = vector([0.01277, 0, 1.903398 - eps], unit='m')
    guide_zero_rot = mccode_quaternion(0, -0.56, 0)

    if use_tcs:
        # Relative to the Target Coordinate System (TCS),
        # The BIFROST Instrument Specific Coordinate System (ISCS) is at:
        tcs_iscs_position = vector([-77.05, 67.72, 137], unit='mm').to(unit='m')
        tcs_iscs_orientation = r(vector([0, 132.14, 0], unit='deg'))
        # But the McStas ESS_butterfly component 'sector': 'W', 'beamline': 4
        # defines its own coordinate system, which is rotated relative to both
        # The ISCS position _in_ the McStas 'W4' coordinates:
        w4_iscs_position = vector([31.38,0,-0.01], unit='mm')
        # In thE TCS coordinate system, W4 focal point is at and oriented:
        w4_orientation = r(vector([0., 132.7, 0.],  unit='deg'))
        w4_position = vector([89, 137., -54], unit='mm').to(unit='m')
        # but we want to move everything to TCS:
        moderator_offset =vector([0, 137., 0], unit='mm').to(unit='m')
        guide_zero_rot = w4_orientation * guide_zero_rot
        guide_zero = at_relative(w4_position, w4_orientation, guide_zero)
    else:
        w4_position = vector([0, 0, 0.], unit='m')
        w4_orientation = r(vector([0, 0, 0.], unit='deg'))

    p['source'] = {
        'sector': 'W',
        'beamline': 4,
        'wavelength_minimum': 'source_lambda_min/"angstrom" = 0.75',
        'wavelength_maximum': 'source_lambda_max/"angstrom" = 30.0',
        'focus_distance': norm(guide_zero),
        'focus_width': (0.068797 + 2 * 0.01277) * m,  # including the substrate?
        'focus_height': 0.03472 * m,
        'position': w4_position,
        'orientation': w4_orientation,
    }

    p.update(primary_compressor_parameters(guide_zero, guide_zero_rot))

    bunker_chopper_height = scalar(0.047514 + 2 * 0.00331, unit='m')  # 2 * margin of error for floor settling in bunker
    hall_chopper_height = scalar(0.09 + 2 * 0.00423, unit='m')  # 2 * margin of error for piles settling under the long guide hall
    radius = 350 * mm
    offset = -(radius - bunker_chopper_height / 2) * vector([0, 1., 0])
    p['pulse_shaping_chopper_1'] = {
        'position': at_relative(p['nose']['end'], p['nose']['orientation'], (0.0306 * m) * z) - offset,
        'orientation': p['nose']['orientation'],
        'radius': radius,
        'height': bunker_chopper_height,
        'angle': scalar(170., unit='deg'),
        'frequency': scalar(14., unit='Hz'),
        'phase': scalar(0., unit='deg'),
        'offset': offset,
    }
    p['pulse_shaping_chopper_2'] = {
        'position': at_relative_dict(p['pulse_shaping_chopper_1'], (0.049 * m) * z),
        'orientation': p['pulse_shaping_chopper_1']['orientation'],
        'radius': radius,
        'height': bunker_chopper_height,
        'angle': scalar(170., unit='deg'),
        'frequency': scalar(14., unit='Hz'),
        'phase': scalar(0., unit='deg'),
        'offset': offset,
    }

    # From BIFROST Table of Optics, ESS-4813238 the end of subsystem 1 to the start
    # of subsystem 2 is exactly 81.707 mm. Private communication indicates instead
    # the gap from the end of the nose-guide to the start of the first curved guide
    # segment inside the PSC housing is 84 mm
    element_6_to_element_5 = 84 * mm
    rel_r = p['nose']['orientation']
    rel_p = at_relative(p['nose']['end'], rel_r, element_6_to_element_5 * z)

    # Element 6 in the old McStas instrument is the curved section. It includes
    # the first and second frame overlap choppers and a copper-substrate 'collimation'
    # section which helps prevent streaming
    el6, rel_p, rel_r = curved_guide_parameters(rel_p, rel_r, bunker_chopper_height)
    p.update(el6)

    # Following the curved section is the expanding 'connector' section including
    # the bunker wall feed through. There is a monitor but no choppers here
    ex, rel_p, rel_r = expanding_guide_parameters(rel_p, rel_r)
    p.update(ex)

    # The straight section includes the bandwidth choppers and a monitor
    ex, rel_p, rel_r = straight_guide_parameters(rel_p, rel_r, hall_chopper_height)
    p.update(ex)

    # The closing section focuses the beam and includes divergence limiting jaws
    ex, rel_p, rel_r = closing_guide_parameters(rel_p, rel_r)
    p.update(ex)
    # The reference point is now the downstream side of the final window.
    # The sample is exactly 578 mm from this position, but there are other things before

    # directly after the guide is an exchangeable B4C mask-aperture.
    p['mask'] = {
        'position': at_relative(rel_p, rel_r, (5 * mm) * z),
        'orientation': rel_r,
        'width': 50 * mm,
        'height': 60 * mm,
    }
    # then the normalization monitor
    p['normalization_monitor'] = {
        'position': at_relative(rel_p, rel_r, (15 * mm) * z),
        'orientation': rel_r,
        'width': 70 * mm,
        'height': 70 * mm,
        'thickness': 0.1 * mm,
    }
    # and finally a driven sample slit (that also can be adjusted along the beam)
    p['slit'] = {
        'position': at_relative(rel_p, rel_r, (30 * mm) * z),
        'orientation': rel_r,
        'width': 70 * mm,
        'height': 70 * mm,
    }

    # The primary spectrometer is followed by the sample stack, then secondary spectrometer
    # the McStas instrument will need numerous extra components around the sample

    p['sample_origin'] = {
        'position': at_relative(rel_p, rel_r, (578 * mm) * z),
        'orientation': rel_r,
    }

    return p