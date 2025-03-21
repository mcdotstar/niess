def primary_compressor_parameters(guide_start_vec, guide_start_rot) -> dict:
    """Parameter dictionary for the pre-Pulse Shaping Chopper guides

    As-designed parameters for the BIFROST primary guide system.
    Can and should be replaced by as-built parameters once known.

    The names of dictionary keys here must match attributes of the Primary
    class, the order should not be important.
    """
    from scipp import scalar, array, sum, vector
    from ..spatial import at_relative

    mm = scalar(1.0, unit='mm').to(unit='m')
    z = vector([0, 0, 1.])

    # verified guide dimensions reported as part of ESS-4019844
    # coating m-values from same, which also has measured reflectivity curves
    bbg_45604 = {
        'length': 482.5 * mm,
        'left': 1.5, # sn_45607_1
        'right': 1.5 , # sn_45607_2
        'top': 2.5, # sn_45606_1
        'bottom': 2.5, # sn_45606_2
        'entry': {
            'inner': {'width': 50.84 * mm, 'height': 48.8 * mm},
            'outer': {'width': 66.84 * mm, 'height': 64.8 * mm}
        },
        'exit': {
            'inner': {'width': 41.78 * mm, 'height': 48.26 * mm},
            'outer': {'width': 57.78 * mm, 'height': 64.26 * mm}
        },
        'horizontal': {
            'major': 4134.2425 * mm, 'minor': 34.817 * mm, 'offset': -2825.03 * mm
        },
        'vertical': {
            'major': 4621.6055 * mm, 'minor': 24.431 * mm, 'offset': -239.795 * mm
        }
    }
    psc_45605 = {
        'length': 389.5 * mm,
        'left': 1.5, # sn_45609_2
        'right': 1.5, # sn_45609_1
        'top': 2.0, # sn_45608_1
        'bottom': 2.0, # sn_45608_2
        'entry': {
            'inner': {'width': 41.28 * mm, 'height': 48.22 * mm},
            'outer': {'width': 57.28 * mm, 'height': 64.22 * mm}
        },
        'exit': {
            'inner': {'width': 30.41 * mm, 'height': 47.37 * mm},
            'outer': {'width': 46.41 * mm, 'height': 63.37 * mm}
        },
        'horizontal': {
            'major': 4134.2425 * mm, 'minor': 34.817 * mm, 'offset': -3329.584 * mm
        },
        'vertical': {
            'major': 4621.6055 * mm, 'minor': 24.431 * mm, 'offset': -744.345 * mm
        }
    }

    p = dict()

    """
    The first part of 'element 6' of the BIFROST primary spectrometer

    The so-called Neutron Beam Optical Assembly, which is a metal-substrate guide
    inserted into the target monolith.
    The guide itself has 1.5 mm aluminum windows at each end, and the monolith
    has a 4 mm window separating the NBOA from the BBG
    """
    nboa_window_thickness = 1.5 * mm
    nboa_input_height = 32.37 * mm
    nboa_input_width = 44.72 * mm
    nboa_substrate = 12.0 * mm
    nboa_output_height = 50.07 * mm  # might be 50.1
    nboa_output_width = 35.32 * mm

    p['nboa_entry_window'] = {
        'position': at_relative(guide_start_vec, guide_start_rot, -nboa_window_thickness * z),
        'orientation': guide_start_rot,
        'length': nboa_window_thickness,
        'composition': 'Al_sg225',
        'width': nboa_input_width + 4 * nboa_substrate,
        'height': nboa_input_height + 4 * nboa_substrate,
    }

    nboa_segments = array(values=[0.48844444, 0.48844444, 0.48844444, 0.48844444,
                                  0.48844444, 0.48844444, 0.48844444, 0.06121889],
                          dims=['segments'], unit='m')
    nboa_bbg_gap = scalar(0.2349, unit='m')
    bbg_nose_gap = scalar(0.015, unit='m')
    # NBOA parameters from original file included the BBG and PSC Nose lengths
    # plus gaps (including windows) -- account for the extra 'missing' lengths here:
    nboa_beyond_out = nboa_bbg_gap + bbg_nose_gap + bbg_45604['length'] + psc_45605['length']
    p['nboa'] = {
        'position': guide_start_vec,
        'orientation': guide_start_rot,
        'length': nboa_segments,
        'left': (3.0, 3.0, 2.5, 2.5, 2.5, 2.0, 1.5, 1.5),
        'right': (3.0, 3.0, 2.5, 2.5, 2.5, 2.0, 1.5, 1.5),
        'top': (3.5, 3.5, 3.0, 3.0, 2.5, 2.5, 2.5, 2.5),
        'bottom': (3.5, 3.5, 3.0, 3.0, 2.5, 2.5, 2.5, 2.5),
        'horizontal': {
            'midpoint': scalar(0.069634, unit='m'),
            'in': scalar(3.4578, unit='m'),
            'out': scalar(0.415155, unit='m') + nboa_beyond_out,
        },
        'vertical': {
            'midpoint': scalar(0.04862, unit='m'),
            'in': scalar(1.36, unit='m'),
            'out': scalar(3.487681, unit='m') + nboa_beyond_out,
        }
    }
    nboa_length = sum(nboa_segments)

    p['nboa_exit_window'] = {
        'position': at_relative(guide_start_vec, guide_start_rot,
                                (nboa_length + nboa_window_thickness) * z),
        'orientation': guide_start_rot,
        'length': nboa_window_thickness,
        'composition': 'Al_sg225',
        'width': nboa_output_width + 4 * nboa_substrate,
        'height': nboa_output_height + 4 * nboa_substrate,
    }

    p['monolith_window'] = {
        'position': at_relative(p['nboa_exit_window']['position'], guide_start_rot,
                                (10 * mm) * z),
        'orientation': guide_start_rot,
        'length': 4 * mm,
        'composition': 'Al_sg225',
        'width': nboa_input_width + 4 * nboa_substrate,
        'height': nboa_input_height + 4 * nboa_substrate,
    }

    """
    The second part of 'element 6' of the BIFROST primary spectrometer

    Part of the shutter assembly just outside the target monolith. When the shutter
    is closed this guide segment is translated out of the beam path and is replaced by
    neutron blocking material.
    This movable section has a window before and after the guide segment.
    """
    p['bbg_entry_window'] = {
        'position': at_relative(p['nboa_exit_window']['position'], guide_start_rot,
                                (nboa_bbg_gap - 2 * mm) * z),
        'orientation': guide_start_rot,
        'length': 0.5 * mm,
        'composition': 'Al_sg225',
        'width': bbg_45604['entry']['outer']['width'],
        'height': bbg_45604['entry']['outer']['height'],
    }

    # The bridge beam guide is a moveable element which exchanges with a shutter
    p['bbg'] = {
        'position':  at_relative(guide_start_vec, guide_start_rot, (sum(nboa_segments) + nboa_bbg_gap) * z),
        'orientation': guide_start_rot,
    }
    p['bbg'].update(bbg_45604)

    p['bbg_exit_window'] = {
        'position': at_relative(p['bbg']['position'], guide_start_rot,
                                (p['bbg']['length'] + 1 * mm) * z),
        'orientation': guide_start_rot,
        'length': 0.5 * mm,
        'composition': 'Al_sg225',
        'width': bbg_45604['exit']['outer']['width'],
        'height': bbg_45604['exit']['outer']['height'],
    }

    """
    The final part of 'element 6' of the BIFROST primary spectrometer

    A segment of focusing guide inside the vacuum housing of the pulse shaping chopper.
    There is an aluminum window upstream into the vacuum housing, but none between
    this guide and the chopper.
    """
    p['psc_housing_entry_window'] = {
        'position': at_relative(p['bbg_exit_window']['position'], guide_start_rot,
                                (bbg_nose_gap - 2 * mm)  * z),
        'orientation': guide_start_rot,
        'length': 0.5 * mm,
        'composition': 'Al_sg225',
        'width': psc_45605['entry']['outer']['width'],
        'height': psc_45605['entry']['outer']['height'],
    }

    # The last guide segment before the PSC, in its vacuum housing
    p['nose'] = {
        'position': at_relative(p['bbg']['position'], guide_start_rot,
                                (p['bbg']['length'] + bbg_nose_gap) * z),
        'orientation': guide_start_rot,
    }
    p['nose'].update(psc_45605)

    # stash the end of this guide element as a reference point for the first PS chopper
    p['nose']['end'] = at_relative(p['nose']['position'], guide_start_rot, p['nose']['length'] * z)
    return p
