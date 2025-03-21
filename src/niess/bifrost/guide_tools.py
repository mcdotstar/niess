from __future__ import annotations

from scipp import Variable
from enum import Enum


class Desc(Enum):
    gap = 1
    device_gap = 2
    window_gap = 3
    unit_gap = 4
    bellow_gap = 5
    boral_mask = 6


class Type(Enum):
    guide = 1
    gap = 2
    window = 3
    mask = 4


def parse_guide_table(table: tuple[tuple[str, Variable],...]):
    import re
#    r = re.compile(r'(?P<guide>(?P<number>[0-9]+)-\sUnit-(?P<id>[0-9]+)\s(?P<name>[a-zA-Z0-9]+))|(?P<gap>[a-z\s]*gap)')
    # Guides are normally '{number}- Unit-{id} {name}' but in at least one case the
    # hyphen after '{number}' is missing, so make it optional.
    r_guide = re.compile(r'(?P<number>[0-9]+)-?\sUnit-(?P<id>[0-9]+)\s(?P<name>[a-zA-Z0-9\s]+)')
    r_gap = re.compile(r'[a-z\s]*gap')
    r_mask = re.compile(r'[a-z\s]*mask')

    def lns(s):
        return s.lower().replace(' ', '_')

    def label_to_key(label):
        if (m := r_guide.match(label)) is not None:
            return Type.guide, int(m.group('number')), int(m.group('id')), lns(m.group('name'))
        if (m := r_gap.match(label)) is not None:
            return Type.gap, Desc[lns(m.group(0))]
        if (m := r_mask.match(label)) is not None:
            return Type.mask, Desc[lns(m.group(0))]
        # fallback on the specified label being a known type
        try:
            return (Type[label], )
        except ValueError:
            raise RuntimeError('Could not parse label "{}"'.format(label))

    return tuple(label_to_key(label) + (length,) for label, length in table)


def straight_unit_dict(ref_p, ref_r, params):
    """
    Construct the dict representation of a guide which is not rotated relative to
    its reference point and orientation, and for which the other guide parameters are
    known. Update the returned reference point to be at the exit of this guide unit.

    :param ref_p:
        The scipp.vector representing the starting point of this guides in the global
        coordinate system
    :param ref_r:
        The scipp.rotation_3 Quaternion representing the starting orientation of
        this guide in the global coordinate system
    :param params:
        A dictionary of parameters representing the guide, with the exception of its
        position or orientation.
    :return:
    """
    from scipp import vector
    from ..spatial import at_relative
    d = {
        'position': ref_p,
        'orientation': ref_r,
    }
    d.update(params)
    # move the reference point to the end of this guide
    if 'length' not in d:
        raise ValueError('Guide length required to move reference point')
    ref_p = at_relative(ref_p, ref_r, d['length'] * vector([0, 0, 1.]))
    return d, ref_p, ref_r


def guide_partial_dict(ref_p, ref_r, table, min_unit, max_unit, unit_function):
    """

    :param ref_p:
        The scipp.vector representing the starting point of this section of guides
        in the global coordinate system
    :param ref_r:
        The scipp.rotation_3 Quaternion representing the starting orientation of
        this section of guides in the global coordinate system
    :param table:
        A parsed table of guide information
    :param min_unit:
        The lower-bound guide unit number to include in this section of guides
    :param max_unit:
        The upper-bound of guide unit number to include in this section of guides
    :param unit_function:
        A function which takes a position, quaternion, and unique guide number and
        returns the dictionary representing that guide, plus the position
        and orientation of the guide *exit*, as a 3-tuple
    :return:
        The collective dictionary representing all guide elements in this guide
        segment, the final guide-exit position, and the final guide-exit orientation.
    """
    from scipp import vector
    from ..spatial import at_relative
    in_section = False
    d = {}
    for entry in table:
        t = entry[0]
        if Type.guide == t:
            in_section = min_unit <= entry[2] <= max_unit
        if in_section:
            if Type.guide == t:
                number, section, name = entry[1:-1]
                d[f'unit_{section}_{name}'], ref_p, ref_r = unit_function(ref_p, ref_r, number, length=entry[-1])
            elif Type.window == entry[0]:
                raise ValueError(f'No windows allowed in continuous section {min_unit}-{max_unit}!')
            else:
                ref_p = at_relative(ref_p, ref_r, entry[-1] * vector([0, 0, 1.]))
        if Type.guide == t:
            in_section = min_unit <= entry[2] < max_unit

    return d, ref_p, ref_r


def device_partial_dict(ref_p: Variable, ref_r: Variable, device: tuple[tuple[str, dict], ...] | None,
                        table, pre_unit, post_unit, al_consts: dict):
    """
    Insert one or more device into an equal number of 'device gaps' in a straight guide

    No orientation change is allowed between devices inserted into subsequent gaps.

    :param ref_p:
        The scipp.vector representing the starting point of this section of non-guides
        in the global coordinate system
    :param ref_r:
        The scipp.rotation_3 Quaternion representing the starting orientation of
        this section of non-guides in the global coordinate system
    :param device:
        A tuple of tuples, each containing the device name and partial dictionary
        representing the device information to be placed into a gap in the guide.
        The order of devices should match the order of device gaps.
    :param table:
        A parsed table of guide information
    :param pre_unit:
        The last guide unit before the section containing the device gap
    :param post_unit:
        The first guide unit after the section containing the device gap
    :param al_consts:
        Any parameters for aluminum windows, exiting the first unit and entering
        the second. Notably the width and height of the windows should be provided,
        their thickness should come from the table but could be overruled here.
    :return:
    """
    from scipp import vector
    from ..spatial import at_relative

    d, section, pre_ok, post_ok, is_exit = {}, 0, False, False, True

    index = 0
    if device is None:
        device = (('LOGICAL_ERROR_IN_' + __file__, {}),)

    for entry in table:
        t = entry[0]
        if Type.guide == t:
            section = entry[2]
            pre_ok = section >= pre_unit
            post_ok = section < post_unit
        if pre_ok and post_ok and Type.guide != t:
            dist = entry[-1]
            if Type.window == t:
                n, s = (section, 'exit') if is_exit else (section + 1, 'entry')
                d[f'unit_{n}_{s}_window'] = {
                    'position': ref_p,
                    'orientation': ref_r,
                    'length': dist,
                    'composition': 'Al_sg225',
                    **al_consts,
                }
                is_exit = False
            elif Type.gap == t and Desc.device_gap == entry[1]:
                dev_name, dev_dict = device[index]
                index += 1

                half_p = at_relative(ref_p, ref_r, dist/2 * vector([0, 0, 1.]))
                if 'offset' in dev_dict:
                    half_p -= dev_dict['offset']
                d[dev_name] = {'position': half_p, 'orientation': ref_r}
                d[dev_name].update(dev_dict)

            ref_p = at_relative(ref_p, ref_r, dist * vector([0, 0, 1.]))

    return d, ref_p, ref_r


def entering_partial_dict(ref_p: Variable, ref_r: Variable,
                          device: tuple[tuple[str, dict], ...] | None,
                          table, al_consts: dict):
    """
    Insert one or more device into an equal number of 'device gaps' in a straight guide
    which all must come before the first guide section in the provided table

    No orientation change is allowed between devices inserted into subsequent gaps.

    :param ref_p:
        The scipp.vector representing the starting point of this section of non-guides
        in the global coordinate system
    :param ref_r:
        The scipp.rotation_3 Quaternion representing the starting orientation of
        this section of non-guides in the global coordinate system
    :param device:
        A tuple of tuples, each containing the device name and partial dictionary
        representing the device information to be placed into a gap in the guide.
        The order of devices should match the order of device gaps.
    :param table:
        A parsed table of guide information
    :param al_consts:
        Any parameters for aluminum windows, exiting the first unit and entering
        the second. Notably the width and height of the windows should be provided,
        their thickness should come from the table but could be overruled here.
    :return:
    """
    from scipp import vector
    from ..spatial import at_relative

    d, section, pre_ok, post_ok, is_exit = {}, 0, False, False, True

    index = 0
    if device is None:
        device = (('LOGICAL_ERROR_IN_' + __file__, {}),)

    # get the section number which we will enter into, for the (presumably) present window
    for entry in table:
        if Type.guide == entry[0]:
            section = entry[2]
            break

    for entry in table:
        t = entry[0]
        if Type.guide == t:
            break
        else:
            dist = entry[-1]
            if Type.window == t:
                d[f'unit_{section}_entry_window'] = {
                    'position': ref_p,
                    'orientation': ref_r,
                    'length': dist,
                    'composition': 'Al_sg225',
                    **al_consts,
                }
                is_exit = False
            elif Type.gap == t and Desc.device_gap == entry[1]:
                dev_name, dev_dict = device[index]
                index += 1

                half_p = at_relative(ref_p, ref_r, dist/2 * vector([0, 0, 1.]))
                if 'offset' in dev_dict:
                    half_p -= dev_dict['offset']
                d[dev_name] = {'position': half_p, 'orientation': ref_r}
                d[dev_name].update(dev_dict)

            ref_p = at_relative(ref_p, ref_r, dist * vector([0, 0, 1.]))

    return d, ref_p, ref_r



def exiting_partial_dict(ref_p: Variable, ref_r: Variable, table, al_consts: dict):
    """
    Insert an aluminum window in a straight guide following the last guide unit

    :param ref_p:
        The scipp.vector representing the starting point of this section of non-guides
        in the global coordinate system
    :param ref_r:
        The scipp.rotation_3 Quaternion representing the starting orientation of
        this section of non-guides in the global coordinate system
    :param table:
        A parsed table of guide information
    :param al_consts:
        Any parameters for aluminum windows, exiting the first unit and entering
        the second. Notably the width and height of the windows should be provided,
        their thickness should come from the table but could be overruled here.
    :return:
    """
    from scipp import vector
    from ..spatial import at_relative

    d, section, pre_ok, post_ok, is_exit = {}, 0, False, False, True

    index = 0

    # get the last section number which we will leave
    for i, entry in enumerate(table):
        if Type.guide == entry[0]:
            section = entry[2]
            index = i

    for entry in table[index:]:
        t = entry[0]
        # No need to worry about the units before the last one, since we use `index`
        if Type.guide != t:
            dist = entry[-1]
            if Type.window == t:
                d[f'unit_{section}_exit_window'] = {
                    'position': ref_p,
                    'orientation': ref_r,
                    'length': dist,
                    'composition': 'Al_sg225',
                    **al_consts,
                }
            ref_p = at_relative(ref_p, ref_r, dist * vector([0, 0, 1.]))

    return d, ref_p, ref_r
