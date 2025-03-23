from scipp import Variable
from scipp import scalar
mm = scalar(1.0, unit='mm').to(unit='m')

"""
The expanding guide section is made up of two copper-substrate guide units which
pass through the Bunker Wall, then eleven glass substrate guide units of possibly
varying material.

The copper guides are (probably) elliptical in construction.
The glass guide are (probably) not elliptical, but instead made of tapered segments
which closely approximate the elliptical geometry.

For now all guide units use the perfect elliptical approximation for expediency.
If necessary, the individual guide segments lengths of each unit are recorded to allow
using the tapered approximation.
"""


def guide_segment_lengths():
    return {
        45717: [249.75 * mm , 500 * mm, 500 * mm, 500 * mm],
        45718: [249.75 * mm , 500 * mm, 500 * mm, 500 * mm],
        45765: [500 * mm , 500 * mm, 500 * mm, 445.1 * mm],
        45766: [500 * mm , 500 * mm, 500 * mm, 445.1 * mm],
        45767: [499.94 * mm, 499.94 * mm, 499.94 * mm, 499.94 * mm],
        45768: [499.94 * mm, 499.94 * mm, 499.94 * mm, 499.94 * mm],
        45769: [499.94 * mm, 499.94 * mm, 499.94 * mm, 499.94 * mm],
        45770: [499.94 * mm, 499.94 * mm, 499.94 * mm, 499.94 * mm],
        45771: [499.94 * mm, 499.94 * mm, 499.94 * mm, 499.94 * mm],
        45772: [499.94 * mm, 499.94 * mm, 499.94 * mm, 499.94 * mm],
        45773: [499.94 * mm, 499.94 * mm, 499.94 * mm, 499.94 * mm],
        45774: [499.94 * mm, 499.94 * mm, 499.94 * mm, 499.94 * mm],
        45775: [500 * mm, 500 * mm, 465.28 * mm]
    }


def guide_unit_parameters():
    """
    Guide parameters taken from the SwissNeutronics drawings from 13 July 2021.
    """
    # Since the ellipse axes are constant through this section, we can add them
    # at the end, so this first dictionary tracks only the unique data per drawing:
    #   {unit number: {length, offset, horizontal m value, vertical m value}}
    values = {
        45717: {'l': 1749.75 * mm, 'o': -24928.98 * mm, 'h': 2.5, 'v': 2.0},
        45718: {'l': 1749.75 * mm, 'o': -23178.73 * mm, 'h': 2.5, 'v': 2.0},
        45765: {'l': 1945.10 * mm, 'o': -21375.98 * mm, 'h': 2.0, 'v': 2.0},
        45766: {'l': 1945.10 * mm, 'o': -19430.38 * mm, 'h': 2.0, 'v': 2.0},
        45767: {'l': 1999.75 * mm, 'o': -17481.28 * mm, 'h': 2.0, 'v': 1.5},
        45768: {'l': 1999.75 * mm, 'o': -15481.03 * mm, 'h': 2.0, 'v': 1.5},
        45769: {'l': 1999.75 * mm, 'o': -13477.28 * mm, 'h': 1.5, 'v': 1.5},
        45770: {'l': 1999.75 * mm, 'o': -11477.03 * mm, 'h': 1.5, 'v': 1.5},
        45771: {'l': 1999.75 * mm, 'o': -9473.28 * mm, 'h': 1.5, 'v': 1.5},
        45772: {'l': 1999.75 * mm, 'o': -7473.03 * mm, 'h': 1.5, 'v': 1.5},
        45773: {'l': 1999.75 * mm, 'o': -5469.28 * mm, 'h': 1.5, 'v': 1.5},
        45774: {'l': 1999.75 * mm, 'o': -3469.03 * mm, 'h': 1.5, 'v': 1.5},
        45775: {'l': 1465.28 * mm, 'o': -1465.28 * mm, 'h': 1.5, 'v': 1.5},
    }
    pars = {
        k: {
            'length': v['l'],
            'vertical': {
                'major': 29352.6625 * mm, 'minor': 45 * mm, 'offset': v['o']
            },
            'horizontal': {
                'major': 28638.5425 * mm, 'minor': 30 * mm, 'offset': v['o']
            },
            'left': v['h'],
            'right': v['h'],
            'top': v['v'],
            'bottom': v['v'],
        } for k, v in values.items()
    }
    return pars


def guide_table():
    from .guide_tools import parse_guide_table
    swissneutronics_37835_expanding_section_table = (
        ('45717- Unit-16 BW insert', 1749.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45718- Unit-17 BW insert', 1749.75 * mm),
        ('window gap', 2.0 * mm),
        ('window', 0.5 * mm),
        ('device gap', 44.5 * mm),
        ('window', 0.5 * mm),
        ('window gap', 2.5 * mm),
        ('boral mask', 3.0 * mm),
        ('45765- Unit-18 expanding', 1945.1 * mm),
        ('unit gap', 0.5 * mm),
        ('45766- Unit-19 expanding', 1945.1 * mm),
        ('bellow gap', 4.0 * mm),
        ('45767- Unit-20 expanding', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45768- Unit-21 expanding', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45769- Unit-22 expanding', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45770- Unit-23 expanding', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45771- Unit-24 expanding', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45772- Unit-25 expanding', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45773- Unit-26 expanding', 1999.75 * mm),
        ('unit gap', 0.5 * mm),
        ('45774- Unit-27 expanding', 1999.75 * mm),
        ('bellow gap', 4.0 * mm),
        ('45775- Unit-28 expanding', 1465.28 * mm),
        ('window gap', 2.5 * mm),
        ('window', 0.5 * mm),
        ('device gap', 114.0 * mm),
    )
    return parse_guide_table(swissneutronics_37835_expanding_section_table)


def unit_dict(ref_p, ref_r, number, length):
    from .guide_tools import straight_unit_dict
    params = guide_unit_parameters()
    return straight_unit_dict(ref_p, ref_r, params[number])


def expanding_guide_parameters(guide_pos, guide_rot) -> tuple[dict, Variable, Variable]:
    # Component order for expanding guide:
    # 1. Copper substrate elliptical guide, Bunker Wall Insert; units 16 & 17
    # 2. Beam monitor 2
    # 3. Glass substrate elliptical-approximation tapered guide segments; units 18-28
    # 4. Shutter to allow entry into the cave without closing the BBG shutter
    from .guide_tools import guide_partial_dict, device_partial_dict, exiting_partial_dict

    table = guide_table()

    p = {}
    bwi, ref_p, ref_r = guide_partial_dict(guide_pos, guide_rot, table, 16, 17, unit_dict)
    p.update(bwi)

    sizes = {'width': 52 * mm, 'height': 72 * mm,}
    device = ('overlap_monitor', {
        'thickness': 0.1 * mm,  # I-BM 100 has a 100 micron thick foil ... plus other stuff in the beam
        'sample_rate': scalar(70., unit='kHz'),
        **sizes,
    })
    d, ref_p, ref_r = device_partial_dict(ref_p, ref_r, (device,), table, 17, 18, sizes)
    p.update(d)

    d, ref_p, ref_r = guide_partial_dict(ref_p, ref_r, table, 18, 28, unit_dict)
    p.update(d)

    beam = {'width': 60 * mm, 'height': 90 * mm}
    window = {k: v + 20 * mm for k, v in beam.items()}
    # there is a shutter in this gap, but there's no need to include it for McStas
    # d, ref_p, ref_r = device_partial_dict(ref_p, ref_r, None, table, 28, 29, window)
    # ignoring that there _is_ a device to be inserted causes a logic error
    d, ref_p, ref_r = exiting_partial_dict(ref_p, ref_r, table, window)
    p.update(d)


    return p, ref_p, ref_r
