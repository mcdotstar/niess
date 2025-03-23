from scipp import scalar, Variable

mm = scalar(1.0, unit='mm').to(unit='m')

def guide_segments():
    length = {
        45823: [183.976 * mm, 500 * mm, 500 * mm, 500 * mm],
        45824: [499.9375 * mm, 499.9375 * mm, 499.9375 * mm, 499.9375 * mm],
        45825: [499.9375 * mm, 499.9375 * mm, 499.9375 * mm, 499.9375 * mm],
        45826: [499.9375 * mm, 499.9375 * mm, 499.9375 * mm, 499.9375 * mm],
        45827: [499.9375 * mm, 499.9375 * mm, 499.9375 * mm, 499.9375 * mm],
        45828: [499.9375 * mm, 499.9375 * mm, 499.9375 * mm, 499.9375 * mm],
        45829: [499.9375 * mm, 499.9375 * mm, 499.9375 * mm, 499.9375 * mm],
        45830: [500 * mm, 500 * mm, 500 * mm, 347.085 * mm],
        45831: [347.085 * mm, 500 * mm, 500 * mm, 500 * mm],
        45832: [500 * mm, 500 * mm, 247.6 * mm, 500 * mm, 500 * mm],
        45833: [500 * mm,  500 * mm, 283 * mm],
        45834: [281.5 * mm, 281.5 * mm],
        45835: [285.25 * mm, 285.25 * mm]
    }
    offset = {
        45823: 0.25 * mm,
        45824: 1688.226 * mm,
        45825: 3688.476 * mm,
        45826: 5692.226 * mm,
        45827: 7692.476 * mm,
        45828: 9696.226 * mm,
        45829: 11696.476 * mm,
        45830: 13700.226 * mm,
        45831: 15547.811 * mm,
        45832: 17398.896 * mm,
        45833: 19663.496 * mm,
        45834: 20963.496 * mm,
        45835: 21543.496 * mm
    }
    horizontal = {
        45823: [1.5, 1.5, 1.5, 1.5],
        45824: [1.5, 1.5, 1.5, 1.5],
        45825: [1.5, 1.5, 1.5, 1.5],
        45826: [1.5, 1.5, 1.5, 1.5],
        45827: [1.5, 1.5, 1.5, 1.5],
        45828: [1.5, 1.5, 1.5, 1.5],
        45829: [1.5, 1.5, 1.5, 1.5],
        45830: [1.5, 1.5, 1.5, 1.5],
        45831: [2.0, 2.0, 2.0, 2.0],
        45832: [2.0, 2.0, 2.0, 2.0, 3.0],
        45833: [3.0, 3.0, 3.0],
        45834: [3.5, 3.5],
        45835: [3.5, 3.5],
    }
    vertical = {
        45823: [1.5, 1.5, 1.5, 1.5],
        45824: [1.5, 1.5, 1.5, 1.5],
        45825: [1.5, 1.5, 1.5, 1.5],
        45826: [1.5, 1.5, 1.5, 1.5],
        45827: [1.5, 1.5, 1.5, 1.5],
        45828: [2.0, 2.0, 2.0, 2.0],
        45829: [2.0, 2.0, 2.0, 2.0],
        45830: [2.0, 2.0, 2.0, 2.0],
        45831: [2.0, 2.0, 2.0, 2.0],
        45832: [2.0, 2.0, 2.0, 2.0, 3.0],
        45833: [3.0, 3.0, 3.0],
        45834: [3.0, 3.0],
        45835: [3.5, 3.5],
    }
    return length, offset, horizontal, vertical


def guide_table():
    from .guide_tools import parse_guide_table
    swissneutronics_37835_closing_guide_section_table = (
        ('45823- Unit-76 closing', 1683.98 * mm),
        ('bellow gap', 4.0 * mm),
        ('45824- Unit-77 closing', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45825- Unit-78 closing', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45826- Unit-79 closing', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45827- Unit-80 closing', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45828- Unit-81 closing', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45829- Unit-82 closing', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45830- Unit-83 closing', 1847.09 * mm),
        ('unit gap', 0.5 * mm),
        ('45831- Unit-84 closing', 1847.09 * mm),
        ('bellow gap', 4.0 * mm),
        ('45832- Unit-85 closing', 2247.6 * mm),
        ('device gap', 17.0 * mm),
        ('45833- Unit-86 closing', 1283.0 * mm),
        ('device gap', 17.0 * mm),
        ('45834- Unit-87 closing', 563.0 * mm),
        ('device gap', 17.0 * mm),
        ('45835- Unit-88 closing', 570.5 * mm),
        ('window gap', 2.5 * mm),
        ('window', 0.5 * mm),
    )
    return parse_guide_table(swissneutronics_37835_closing_guide_section_table)

def guide_unit_parameters():
    values = {
        45823: {'l': 1683.976 * mm, 'o': 0.25 * mm, 'h': 1.5, 'v': 1.5},
        45824: {'l': 1999.75 * mm, 'o': 1688.226 * mm, 'h': 1.5, 'v': 1.5},
        45825: {'l': 1999.75 * mm, 'o': 3688.476 * mm, 'h': 1.5, 'v': 1.5},
        45826: {'l': 1999.75 * mm, 'o': 5692.226 * mm, 'h': 1.5, 'v': 1.5},
        45827: {'l': 1999.75 * mm, 'o': 7692.476 * mm, 'h': 1.5, 'v': 1.5},
        45828: {'l': 1999.75 * mm, 'o': 9696.226 * mm, 'h': 1.5, 'v': 2.0},
        45829: {'l': 1999.75 * mm, 'o': 11696.476 * mm, 'h': 1.5, 'v': 2.0},
        45830: {'l': 1847.085 * mm, 'o': 13700.226 * mm, 'h': 1.5, 'v': 2.0},
        45831: {'l': 1847.085 * mm, 'o': 15547.811 * mm, 'h': 2.0, 'v': 2.0},
        45832: {'l': 2247.6 * mm, 'o': 17398.896 * mm, 'h': 2.0, 'v': 2.0}, # actually mixed m=3 and m=2 :(
        45833: {'l': 1283 * mm, 'o': 19663.496 * mm, 'h': 3.0, 'v': 3.0},
        45834: {'l': 563 * mm, 'o': 20963.496 * mm, 'h': 3.5, 'v': 3.0},
        45835: {'l': 570.5 * mm, 'o': 21543.496 * mm, 'h': 3.5, 'v': 3.5},
    }
    pars = {
        k: {
            'length': v['l'],
            'vertical': {
                'major': 23034.477 * mm, 'minor': 45 * mm, 'offset': v['o']
            },
            'horizontal': {
                'major': 24364.5605 * mm, 'minor': 30 * mm, 'offset': v['o']
            },
            'left': v['h'],
            'right': v['h'],
            'top': v['v'],
            'bottom': v['v'],
        } for k, v in values.items()
    }
    return pars


def unit_dict(ref_p, ref_r, number, length):
    from .guide_tools import straight_unit_dict
    params = guide_unit_parameters()
    return straight_unit_dict(ref_p, ref_r, params[number])


def closing_guide_parameters(guide_pos, guide_rot) -> tuple[dict, Variable, Variable]:
    from .guide_tools import guide_partial_dict, device_partial_dict
    table = guide_table()
    p = {}
    window = {'width': 60 * mm, 'height': 90 * mm}  # bigger tha the beam for sure

    ref_p, ref_r = guide_pos, guide_rot
    for min_unit, max_unit, no in ((76, 85, 3), (86, 86, 2), (87, 87, 1)):
        d, ref_p, ref_r = guide_partial_dict(ref_p, ref_r, table, min_unit, max_unit, unit_dict)
        p.update(d)
        # horizontal-only divergence limiting 'jaw'
        device = (f'jaw_{no}', window.copy())
        d, ref_p, ref_r = device_partial_dict(ref_p, ref_r, (device,), table, max_unit, max_unit+1,
                                              window)
        p.update(d)

    d, ref_p, ref_r = guide_partial_dict(ref_p, ref_r, table, 88, 88, unit_dict)
    p.update(d)

    d, ref_p, ref_r = device_partial_dict(ref_p, ref_r, None, table, 88, 89, window)
    p.update(d)

    # The sample is 578 mm from the current reference point (the downstream side of the
    # final aluminum window)

    return p, ref_p, ref_r