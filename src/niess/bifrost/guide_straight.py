from scipp import scalar, Variable

mm = scalar(1.0, unit='mm').to(unit='m')
bandwidth_monitor = 15 * mm
attenuator_1 = 5 * mm
attenuator_2 = 10 * mm
attenuator_3 = 3 * mm

def guide_table():
    from .guide_tools import parse_guide_table

    after_bwc_device_gap = 63.5 * mm

    gap_pre_bandwidth_monitor = 2 * mm  # FIXME this must be verified
    gap_bandwidth_monitor_attenuator_1 = 2 * mm
    gap_attenuator_1_attenuator_2 = 2 * mm
    gap_attenuator_2_attenuator_3 = 2 * mm
    gap_post_attenuator_3 = after_bwc_device_gap - (
        gap_pre_bandwidth_monitor + bandwidth_monitor
        + gap_bandwidth_monitor_attenuator_1 + attenuator_1
        + gap_attenuator_1_attenuator_2 + attenuator_2
        + gap_attenuator_2_attenuator_3 + attenuator_3
    )


    swissneutronics_37835_straight_guide_section_table = (
        ('window', 0.5 * mm),
        ('window gap', 2.5 * mm),
        ('boral mask', 3.0 * mm),
        ('45776- Unit-29 straight', 1945.1 * mm),
        ('unit gap', 0.5 * mm),
        ('45777- Unit-30 straight', 1945.1 * mm),
        ('bellow gap', 4.0 * mm),
        ('45778- Unit-31 straight', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45779- Unit-32 straight', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45780- Unit-33 straight', 1781.89 * mm),
        ('unit gap', 0.5 * mm),
        ('45781- Unit-34 straight', 1781.89 * mm),
        ('bellow gap', 4.0 * mm),
        ('45782- Unit-35 straight', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45783- Unit-36 straight', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45784- Unit-37 straight', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45785- Unit-38 straight', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45786- Unit-39 straight', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45787- Unit-40 straight', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45788- Unit-41 straight', 1936.88 * mm),
        ('unit gap', 0.5 * mm),
        ('45789- Unit-42 straight', 1936.88 * mm),
        ('unit gap', 0.5 * mm),
        ('45790- Unit-43 straight', 1171.2 * mm),

        # ('device gap', 160.0 * mm),  # old idea to have monitor in vacuum

        ('unit gap', 24 * mm), # end of Unit-24 to first BWC disc
        ('device gap', 11 * mm), # width of first BWC disc
        ('unit gap', 24 * mm), # estimated gap from first disc to second disc
        ('device gap', 11 * mm), # second BWC disc width
        ('window gap', 24 * mm),
        ('window', 0.5 * mm),
        # ('device gap', 63.5 * mm), # location of bandwidth monitor then attenuators
        ('gap', gap_pre_bandwidth_monitor),
        ('device gap', bandwidth_monitor),
        ('gap', gap_bandwidth_monitor_attenuator_1),
        ('device gap', attenuator_1),  # 5 mm Plexiglass
        ('gap', gap_attenuator_1_attenuator_2),
        ('device gap', attenuator_2), # 10 mm Plexiglass
        ('gap', gap_attenuator_2_attenuator_3),
        ('device gap', attenuator_3), # 3 mm B4C with 68 2 mm diameter holes
        ('gap', gap_post_attenuator_3),

        ('window', 0.5 * mm),
        ('window gap', 2.5 * mm),

        ('boral mask', 3.0 * mm),
        ('45791 Unit-44 straight', 1406.4 * mm),
        ('unit gap', 0.5 * mm),
        ('45792- Unit-45 straight', 1406.4 * mm),
        ('bellow gap', 4.0 * mm),
        ('45793- Unit-46 straight', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45794- Unit-47 straight', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45795- Unit-48 straight', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45796- Unit-49 straight', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45797- Unit-50 straight', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45798- Unit-51 straight', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45799- Unit-52 straight', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45800- Unit-53 straight', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45801- Unit-54 straight', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45802- Unit-55 straight', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45803- Unit-56 straight', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45804- Unit-57 straight', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45805- Unit-58 straight', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45806- Unit-59 straight', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45807- Unit-60 straight', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45808- Unit-61 straight', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45809- Unit-62 straight', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45810- Unit-63 straight', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45811- Unit-64 straight', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45812- Unit-65 straight', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45813- Unit-66 straight', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45814 Unit-67 straight', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45815- Unit-68 straight', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45816- Unit-69 straight', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45817- Unit-70 straight', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45818- Unit-71 straight', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45819- Unit-72 straight', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45820- Unit-73 straight', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45821- Unit-74 straight', 1000.0 * mm),
        ('bellow gap', 4.0 * mm),
        ('45822- Unit-75 straight', 1311.52 * mm),
        ('unit gap', 0.5 * mm),
    )
    return parse_guide_table(swissneutronics_37835_straight_guide_section_table)


def unit_dict(ref_p, ref_r, number, length):
    # The straight guide is made up of entirely equivalent guide units
    from .guide_tools import straight_unit_dict
    params = {
        'width': 60 * mm,
        'height': 90 * mm,
        'left': 1.5,
        'right': 1.5,
        'top': 1.5,
        'bottom': 1.5,
        'length': length,
    }
    return straight_unit_dict(ref_p, ref_r, params)


def straight_guide_parameters(guide_pos, guide_rot, chopper_height) -> tuple[dict, Variable, Variable]:
    from scipp import array, vector
    from .guide_tools import guide_partial_dict, device_partial_dict, entering_partial_dict
    table = guide_table()
    beam = {'width': 60 * mm, 'height': 90 * mm}
    window = {k: v + 20 * mm for k, v in beam.items()}

    # finish the gap left for the shutter
    p, ref_p, ref_r = entering_partial_dict(guide_pos, guide_rot, None, table, window)

    # straight guide from shutter to bandwidth chopper
    d, ref_p, ref_r = guide_partial_dict(ref_p, ref_r, table, 29, 43, unit_dict)
    p.update(d)

    radius = 350 * mm
    offset = -(radius - chopper_height / 2) * vector([0, 1.0, 0])
    chopper = {
        'radius': 350 * mm,
        'height': chopper_height,
        'angle': scalar(161.0, unit='deg'),
        'frequency': scalar(14.0, unit='Hz'),
        'phase': scalar(0., unit='deg'),
        'offset': offset,
    }

    plexiglass = 'AcrylicGlass_C5O2H8'
    b4c = 'B4C_sg166_BoronCarbide' # TODO check whether this should be *enriched* 10B, https://github.com/mctools/ncrystal/discussions/286
    attenuator = {'width': 88 * mm, 'height': 105 * mm, 'composition': plexiglass}

    devices = (
        ('bandwidth_chopper_1', {**chopper}),
        ('bandwidth_chopper_2', {**chopper}),
        ('bandwidth_monitor', {'thickness': bandwidth_monitor, 'sample_rate': scalar(42., unit='kHz'), **beam}),
        ('attenuator_1', {'length': attenuator_1, **attenuator}),
        ('attenuator_2', {'length': attenuator_2, **attenuator}),
        ('attenuator_3', {'length': attenuator_3, **attenuator, 'composition': b4c}),
    )
    d, ref_p, ref_r = device_partial_dict(ref_p, ref_r, devices, table, 43, 44, window)
    p.update(d)

    # straight guide from after monitor to the start of the closing section
    d, ref_p, ref_r = guide_partial_dict(ref_p, ref_r, table, 44, 76, unit_dict)
    p.update(d)

    return p, ref_p, ref_r