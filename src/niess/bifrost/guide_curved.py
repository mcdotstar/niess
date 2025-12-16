from scipp import Variable, scalar

from niess.spatial import at_relative_dict

def radius_of_curvature_to_rotation_angle(distance: Variable, radius_of_curvature: Variable) -> Variable:
    """
    Straight segments approximating a curve must be rotated proportional to their length
    """
    from scipp import atan2
    return atan2(y=distance.to(unit=radius_of_curvature.unit)/2, x=radius_of_curvature) * 2


def radius_of_curvature_to_rotation(distance: Variable, radius_of_curvature: Variable) -> Variable:
    """Return the correct quaternion to rotate a BIFROST curved guide element"""
    # TODO verify rotation direction around y
    from scipp import vector
    from scipp.spatial import rotations_from_rotvecs
    theta = radius_of_curvature_to_rotation_angle(distance, radius_of_curvature)
    return rotations_from_rotvecs(theta * vector([0, 1, 0.]))


def half_rotation(rot: Variable) -> Variable:
    from scipp.spatial import rotation
    from scipy.spatial.transform import Rotation
    identity = rotation(value=[0, 0, 0, 1])
    half_rot = rotation(value=Rotation.from_quat(rot.value + identity.value).as_quat())
    return half_rot


def guide_rotated_position(axis: Variable, width: Variable, rot: Variable) -> Variable:
    """Define the position where a rotated guide just touches the corner of the
    previous guide
    :param axis: the symmetry axis of the guide
    :param width: the width of the guide in the direction perpendicular to the
                  guide symmetry axis and the rotation axis
    :param rot: the rotation quaternion of the guide
    """
    from scipp import acos, sin, scalar
    #   *       ..--*     The vector forms a chord of the circle centered on one
    #   |    .-^  .^      edge of the guide, with radius equal to the half of the
    #   | .-^ .--^        width of the guide. It is rotated by the rotation angle
    #   |=--^'            away from the symmetry axis of the guide, such that it has
    #                     distance = 2 * width/2 * sin(angle/2)
    # -> Find the angle of half of the rotation, take its sin, multipy by the width
    # scalar part of quaternion = cos(angle/2)
    distance = 2 * width * sin(acos(scalar(half_rotation(rot).value[-1])))
    return distance * (rot * axis)


def curved_guide_unit_dictionary(start_at, start_rot, lengths, name, radius_of_curvature, **consts):
    """consts _must_ include 'width' and 'height'"""
    from scipp import vector, scalar
    um = scalar(1.0, unit='micrometer').to(unit='m')
    # The local guide direction is _always_ [001]
    z = vector([0, 0, 1.])
    x = vector([1., 0, 0])
    d = {
        f'{name}_guide_{i}': {'length': length, **consts}
        for i, length in enumerate(lengths)
    }

    def end_corner_rot(which):
        w = d[which]
        ll, ww, rt = [w[n] for n in ('length', 'width', 'orientation')]
        return at_relative_dict(w, ll * z + ww * x), rt

    this = f'{name}_guide_0'
    d[this]['position'] = start_at
    d[this]['orientation'] = start_rot
    for i, length in enumerate(lengths[1:]):
        corner, rot = end_corner_rot(this)
        this = f'{name}_guide_{i+1}'
        new_rot = radius_of_curvature_to_rotation(length, radius_of_curvature)
        tot_rot = new_rot * rot
        width = d[this]['width']
        d[this]['position'] = corner + tot_rot * (-width * x)
        d[this]['orientation'] = tot_rot
    end = at_relative_dict(d[this], d[this]['length'] * z)

    # Fudge the guide length to ensure there's no overlap on the inner corners
    for n in d:
        d[n]['length'] -= 10 * um

    return d, end, d[this]['orientation']


def curved_guide_partial_dict(ref_p, ref_r, radius, table, lengths, min_unit, max_unit, **consts):
    from scipp import vector
    from .guide_tools import Type, parse_guide_table
    from ..spatial import at_relative
    in_section = False
    section = 0
    d = {}
    for entry in parse_guide_table(table):
        if Type.guide == entry[0]:
            in_section = min_unit <= entry[2] <= max_unit
            section = entry[2]
        if in_section:
            if Type.guide == entry[0]:
                ttype, number, identifier, name, length = entry
                fname = f'unit_{section}_{name}'
                # lengths is a integer-keyed dictionary, we pick the right one
                d[fname], ref_p, ref_r = curved_guide_unit_dictionary(
                    ref_p,
                    radius_of_curvature_to_rotation(lengths[section][0], radius) * ref_r,
                    lengths[section],
                    fname,
                    radius,
                    **consts
                )
            elif Type.window == entry[0]:
                raise ValueError('No windows in continuous sections!')
            else:
                # a gap, update the position
                ref_p = at_relative(ref_p, ref_r, entry[2] * vector([0, 0, 1.]))
        if Type.guide == entry[0]:
            # After the Unit-8 guide, we are not _in_ the section any longer
            in_section = min_unit <= entry[2] < max_unit

    return d, ref_p, ref_r

def curved_guide_device_partial_dict(ref_p, ref_r, dev_name, dev_dict, table, pre_unit, post_unit, **consts):
    from scipp import vector
    from .guide_tools import Desc, Type, parse_guide_table
    from ..spatial import at_relative
    section = 0
    d = {}
    pre_ok = False
    post_ok = False
    is_exit = True
    for entry in parse_guide_table(table):
        if Type.guide == entry[0]:
            pre_ok = entry[2] >= pre_unit
            post_ok = entry[2] < post_unit
            section = entry[2]
        if pre_ok and post_ok and Type.guide != entry[0]:
            dist = entry[-1]
            if Type.window == entry[0]:
                n, s = (section, 'exit') if is_exit else (section + 1, 'entry')
                d[f'unit_{n}_{s}_window'] = {
                    'position': ref_p,
                    'orientation': ref_r,
                    'length': dist,
                    'composition': 'Al_sg225',
                    **consts
                }
                is_exit = False
            elif Type.gap == entry[0]:
                if Desc.device_gap == entry[1]:
                    # For lack of better information, position the device in the
                    # center of the gap left for it:
                    half_p = at_relative(ref_p, ref_r, dist/2 * vector([0, 0, 1.]))
                    if 'offset' in dev_dict:
                        half_p -= dev_dict['offset']
                    d[dev_name] = {'position': half_p, 'orientation': ref_r}
                    d[dev_name].update(dev_dict)
            else:
                raise ValueError('Only windows or gaps expected here!')
            ref_p = at_relative(ref_p, ref_r, dist * vector([0, 0, 1.]))

    return d, ref_p, ref_r


def curved_guide_parameters(guide_start_vec, guide_start_rot, bunker_chopper_height) -> tuple[dict, Variable, Variable]:
    """
    Parameter dictionary for the post-Pulse Shaping Chopper guides

    As-designed parameters for the BIFROST primary guide system.
    Can and should be replaced by as-built parameters once known.

    The names of dictionary keys here must match attributes of the Primary
    class, the order should not be important.
    """
    from scipp import scalar, vector, array
    from ..spatial import at_relative, at_relative_dict
    m = scalar(1.0, unit='m')
    mm = scalar(1.0, unit='mm').to(unit='m')

    # Described in ESS-1075014, section 3.3

    # Sub-Section 2 is the curved guide after the Pulse Shaping chopper.
    #
    # The order of components is:
    # 1. Segment of guide inside the PSC housing, 'unit 3'
    # 2. PSC guide housing window
    # 3. First beam monitor, a fission chamber that is 15 mm thick.
    #    The gap it sits in may be bigger -- apparently 50 mm, probably including both windows.
    # 4. Aluminum entrance window
    # 5. guide unit 4; segments offset and oriented to approximate a curve
    # 6. First frame-overlap chopper (connected to up-steam and down-stream housing without a window?).
    # 7. guide units 5-8; segments offset and oriented to approximate a curve
    # 8. Second frame-overlap chopper
    # 9. guide units 9-15; segments offset and oriented to approximate a curve

    # Taken from SwissNeutronics drawings for guide sub-assemblies from 2021-07-01
    curved_guide_unit_labels = {
        3: 45752, 4: 45753, 5: 45754, 6: 45755, 7: 45756, 8: 45757, 9: 45758,
        10: 45759, 11: 45760, 12: 45761, 13: 45762, 14: 45763, 15: 45764
    }
    curved_guide_unit_lengths = {
        3: [389.5 * mm],
        4: [500.0 * mm, 500.0 * mm, 500.0 * mm, 177.35 * mm],
        5: [502.78 * mm, 502.78 * mm, 502.78 * mm],
        6: [500.0 * mm, 500.0 * mm, 500.0 * mm, 140 * mm],
        7: [118.3 * mm, 500.0 * mm, 500.0 * mm, 500.0 * mm],
        8: [500.0 * mm, 500.0 * mm, 118.3 * mm, 500.0 * mm],
        9: [500.0 * mm, 500.0 * mm, 68.3 * mm, 500.0 * mm],
        10: [175.71 * mm, 351.42 * mm, 351.42 * mm, 175.71 * mm], # Cu substrate
        11: [236.32 * mm, 472.63 * mm, 236.32 * mm], # Cu substrate
        12: [500.0 * mm, 500.0 * mm, 448.22 * mm],
        13: [500.0 * mm, 500.0 * mm, 448.22 * mm],
        14: [500.0 * mm, 500.0 * mm, 448.22 * mm],
        15: [500.0 * mm, 500.0 * mm, 448.22 * mm],
    }
    swissneutronics_37835_curved_section_table = (
        ('45604- Unit-1 BBG', 482.5 * mm),
        ('gap', 22.05 * mm),
        ('45605- Unit-2 PSC', 389.5 * mm),
        ('gap', 81.71 * mm),  # PSC1 and PSC2
        ('45752- Unit-3 curved', 389.5 * mm),
        ('device gap', 47.0 * mm),  # PSC fission chamber monitor
        ('window', 0.5 * mm),
        ('window gap', 2.5 * mm),
        ('45753- Unit-4 curved', 1677.35 * mm),
        ('window gap', 2.5 * mm),
        ('window', 0.5 * mm),
        ('device gap', 47.0 * mm),  # FOC1
        ('window', 0.5 * mm),
        ('window gap', 2.5 * mm),
        ('45754- Unit-5 curved', 1508.35 * mm),
        ('unit gap', 0.5 * mm),
        ('45755- Unit-6 curved', 1640.0 * mm),
        ('bellow gap', 4.0 * mm),
        ('45756- Unit-7 curved', 1618.3 * mm),
        ('unit gap', 0.5 * mm),
        ('45757- Unit-8 curved', 1618.3 * mm),
        ('window gap', 2.5 * mm),
        ('window', 0.5 * mm),
        ('device gap', 59.0 * mm),  # FOC2 + monitor?
        ('window', 0.5 * mm),
        ('unit gap', 2.5 * mm),
        ('45758- Unit-9 curved', 1568.3 * mm),
        ('unit gap', 0.5 * mm),
        ('45759- Unit-10 curved', 1054.25 * mm),
        ('unit gap', 0.5 * mm),
        ('45760- Unit-11 curved', 945.25 * mm),
        ('bellow gap', 4.0 * mm),
        ('45761- Unit-12 curved', 1448.22 * mm),
        ('unit gap', 0.5 * mm),
        ('45762- Unit-13 curved', 1448.22 * mm),
        ('bellow gap', 4.0 * mm),
        ('45763- Unit-14 curved', 1448.22 * mm),
        ('unit gap', 0.5 * mm),
        ('45764- Unit-15 curved', 1448.22 * mm),
        ('unit gap', 0.5 * mm),
    )

    # Key values, taken from ESS-1075014 Figure 5 Curved section optical summary
    radius_of_curvature = 1518500 * mm  # as designed
    beam_monitor_1_gap = 50 * mm
    beam_monitor_1_gap = swissneutronics_37835_curved_section_table[5][1] # 47 mm

    entry_to_foc1_gap = 2116.7 * mm
    foc1_gap = 65 * mm
    entry_to_foc2_gap = 8559.75 * mm
    foc2_gap = 65 * mm
    entry_to_collimation_section = 10195.5 * mm
    collimation_section = 2000 * mm  # copper-substrate, 300 mm with thicker walls?
    entry_to_exit = 17995.28 * mm
    coatings = {'left': 3.0, 'right': 3.5, 'top': 2.5, 'bottom': 2.5}

    guide_width = 29.53 * mm
    guide_height = 47.51 * mm

    p = dict()
    y = vector([0, 1., 0])
    z = vector([0, 0, 1.])

    p['unit_3_curved'], last_p, last_r = curved_guide_unit_dictionary(
        guide_start_vec, guide_start_rot,
        curved_guide_unit_lengths[3],
        'unit_3_curved',
        radius_of_curvature,
        width=guide_width,
        height=guide_height,
        **coatings,
    )

    window_thickness = 0.5 * mm
    window_gap = 2.5 * mm
    # This window does not appear to be in the SwissNeutronics optics table
    p['psc_exit_window'] = {
        'position': at_relative(last_p, last_r, window_gap * z),
        'orientation': last_r,
        'length': window_thickness,
        'width':  2 * guide_width,
        'height': 2 * guide_height,
        'composition': 'Al_sg225',
    }

    device_gap = swissneutronics_37835_curved_section_table[5][1]
    window_thickness = swissneutronics_37835_curved_section_table[6][1]
    window_gap = swissneutronics_37835_curved_section_table[7][1]

    p['psc_monitor'] = {
        'position': at_relative(last_p, last_r, device_gap/2 * z),
        'orientation': last_r,
        'thickness': window_thickness,
        'width': 2 * guide_width,
        'height': 2 * guide_height,
    }

    p['curved_entrance_window'] = {
        'position': at_relative(last_p, last_r, device_gap * z),
        'orientation': last_r,
        'length': window_thickness,
        'width': guide_width,
        'height': guide_height,
        'composition': 'Al_sg225',
    }
    # StraightGuides following radius of curvature, between PSC and FOC1
    p['unit_4_curved'], last_p, last_r = curved_guide_unit_dictionary(
        at_relative(last_p, last_r, (device_gap + window_thickness + window_gap) * z),
        radius_of_curvature_to_rotation(curved_guide_unit_lengths[4][0], radius_of_curvature) * last_r,
        curved_guide_unit_lengths[4],
        'unit_4_curved',
        radius_of_curvature,
        width=guide_width,
        height=guide_height,
        **coatings,
    )

    # SwissNeutronics table indicates that there is a window exiting Unit 4
    window_gap = swissneutronics_37835_curved_section_table[9][1]
    window_thickness = swissneutronics_37835_curved_section_table[10][1]
    p['unit_4_exit_window'] = {
        'position': at_relative(last_p, last_r, window_gap * z),
        'orientation': last_r,
        'length': window_thickness,
        'width': guide_width,
        'height': guide_height,
        'composition': 'Al_sg225',
    }
    # Move the reference point to the downstream side of the window
    last_p = at_relative_dict(p['unit_4_exit_window'], window_thickness * z)

    # then the first Frame Overlap Chopper
    device_gap = swissneutronics_37835_curved_section_table[11][1]
    radius = 350 * mm
    offset = -(radius - bunker_chopper_height / 2) * y
    p['frame_overlap_chopper_1'] = {
        'position': at_relative(last_p, last_r, device_gap/2 * z) - offset,
        'orientation': last_r,
        'radius': radius,
        'height': bunker_chopper_height,
        'angle': scalar(38.26, unit='deg'),
        'frequency': scalar(14.0, unit='Hz'),
        'phase': scalar(0., unit='deg'),
        'offset': offset,
    }

    # And then a window before Unit 5
    window_thickness = swissneutronics_37835_curved_section_table[12][1]
    window_gap = swissneutronics_37835_curved_section_table[13][1]
    p['unit_5_entry_window'] = {
        'position': at_relative(last_p, last_r, device_gap * z),
        'orientation': last_r,
        'length': window_thickness,
        'width': guide_width,
        'height': guide_height,
        'composition': 'Al_sg225',
    }
    # Move the reference point from the Unit-4 exit window to the start of Unit-5
    last_p = at_relative_dict(p['unit_5_entry_window'], (window_thickness + window_gap) * z)

    # Units between FOC1 and FOC2 are # 5, 6, 7, 8
    section, last_p, last_r = curved_guide_partial_dict(
        last_p, last_r, radius_of_curvature, swissneutronics_37835_curved_section_table,
        curved_guide_unit_lengths,
        5, 8, width=guide_width, height=guide_height, **coatings
    )
    p.update(section)
    # The reference point and reference orientation were last moved
    # to the down-stream end of Unit-8

    foc = {
        'radius': radius,
        'height': bunker_chopper_height,
        'angle': scalar(52.01, unit='deg'),
        'frequency': scalar(14.0, unit='Hz'),
        'phase': scalar(0., unit='deg'),
        'offset': offset,
    }
    section, last_p, last_r = curved_guide_device_partial_dict(
        last_p, last_r, 'frame_overlap_chopper_2', foc,
        swissneutronics_37835_curved_section_table, 8, 9,
        width=guide_width, height=guide_height, **coatings
    )
    p.update(section)
    # reference point moved to after last gap, so position of guide Unit 9

    section, last_p, last_r = curved_guide_partial_dict(
        last_p, last_r, radius_of_curvature, swissneutronics_37835_curved_section_table,
        curved_guide_unit_lengths,
        9, 16, width=guide_width, height=guide_height, **coatings
    )
    p.update(section)
    # reference point and rotation updated to after guide Unit 15 post-unit gap
    # Note that above call specifies max_unit 16 which is not in this table in order
    # to ensure that the 0.5 mm gap is included

    return p, last_p, last_r