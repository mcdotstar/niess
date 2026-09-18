"""Calibration data for the teaching instrument.

This is the shape every instrument submodule's ``parameters.py`` takes: nested plain
dictionaries whose values are :mod:`scipp` ``Variable``s carrying real units. Nothing
here converts to metres or degrees -- that happens once, at the ``__mccode__``
boundary -- so these numbers can be read straight off an engineering drawing.

Positions are *chained*: each section builder receives the position and orientation of
the element before it, places its own components relative to that, and returns the
reference for whatever comes next. That is the direct analogue of a McStas
``AT (0, 0, d) RELATIVE previous`` chain, and it means a change upstream moves
everything downstream without any number being written twice.
"""
from scipp import scalar, vector
from scipp.spatial import rotations_from_rotvecs

from ..components.chopper import disc_beam_offset
from ..spatial import at_relative

#: Multiply a number by this to express it in millimetres, as drawings do.
mm = scalar(1.0, unit='mm').to(unit='m')

#: The beam direction, for chaining positions along the instrument.
z = vector([0, 0, 1.0])


def _unrotated():
    return rotations_from_rotvecs(vector([0, 0, 0.0], unit='deg'))


def source_parameters():
    """The moderator, at the origin of the instrument coordinate system.

    ``wavelength_minimum`` and ``wavelength_maximum`` are McCode instrument-parameter
    specifications rather than values: they become ``DEFINE INSTRUMENT`` arguments, so
    the wavelength band is selectable at run time without rebuilding the instrument.
    """
    return {
        'name': 'source',
        'position': vector([0, 0, 0.0], unit='m'),
        'orientation': _unrotated(),
        'sector': 'W',
        'beamline': 4,
        'height': scalar(3.0, unit='cm'),
        'cold_fraction': 0.5,
        'wavelength_minimum': 'source_lambda_min/"angstrom" = 0.75',
        'wavelength_maximum': 'source_lambda_max/"angstrom" = 5.0',
    }


def guide_parameters(ref_p, ref_r):
    """Two straight guide units in their own section.

    Returns the section dictionary plus the position and orientation of its exit, for
    the next element to be placed against.
    """
    lengths = (2000 * mm, 3000 * mm)
    gap = 10 * mm
    width, height = 40 * mm, 60 * mm

    entry_at = at_relative(ref_p, ref_r, 1500 * mm * z)
    exit_at = at_relative(ref_p, ref_r, (1500 * mm + lengths[0] + gap) * z)

    section = {
        'unit_1': {
            'name': 'unit_1',
            'position': entry_at,
            'orientation': ref_r,
            'length': lengths[0],
            'width': width,
            'height': height,
            'm': 2.0,
        },
        'unit_2': {
            'name': 'unit_2',
            'position': exit_at,
            'orientation': ref_r,
            'length': lengths[1],
            'width': width,
            'height': height,
            'm': 3.0,
        },
    }
    end = 1500 * mm + lengths[0] + gap + lengths[1]
    return section, at_relative(ref_p, ref_r, end * z), ref_r


def chopper_parameters(ref_p, ref_r):
    """A single-window disc chopper.

    ``DiscChopper`` declares ``{name}speed`` and ``{name}delay`` as instrument
    parameters, so both are run-time settable -- which is what makes them appear in the
    NeXus output as links to an ``NXlog`` rather than as fixed numbers.
    """
    at = at_relative(ref_p, ref_r, 250 * mm * z)
    # `position` is the spindle and the emitted AT is the beam crossing, so the disc
    # centre sits above the beam by as much as `beam_angle` brings it back down. Same
    # formula the chopper uses to go the other way, negated.
    radius, height = 350 * mm, 60 * mm
    beam_angle = scalar(180.0, unit='deg')
    spindle = -disc_beam_offset(
        radius=radius,
        height=height,
        beam_angle=beam_angle
    )
    parameters = {
        'name': 'chopper',
        'position': at + spindle,
        'orientation': ref_r,
        'radius': radius,
        'angle': scalar(170.0, unit='deg'),
        'frequency': scalar(14.0, unit='Hz'),
        'delay': scalar(0.0, unit='s'),
        'height': height,
        'width': 40 * mm,
        # The disc hangs above the beam, so the beam crosses at the bottom of it: half a
        # turn from the zero mark, which sits on +y. That is enough to place it -- the
        # offset follows from the angles, the radius and the slit height.
        'beam_angle': beam_angle,
    }
    return parameters, at, ref_r


def jaw_parameters(ref_p, ref_r):
    """A variable-width jaw. Its opening is a pair of instrument parameters."""
    at = at_relative(ref_p, ref_r, 500 * mm * z)
    return {
        'name': 'jaw',
        'position': at,
        'orientation': ref_r,
        'width': 30 * mm,
        'height': 50 * mm,
    }, at, ref_r


def monitor_parameters(ref_p, ref_r):
    """A beam monitor. Its histogram stream configuration is attached automatically."""
    at = at_relative(ref_p, ref_r, 200 * mm * z)
    return {
        'name': 'monitor',
        'position': at,
        'orientation': ref_r,
        'width': 50 * mm,
        'height': 50 * mm,
        'thickness': 1 * mm,
    }, at, ref_r


# --8<-- [start:chain]
def teaching_parameters():
    """Every number the teaching instrument needs.

    The keys must match ``Primary``'s field names; their order is irrelevant, since
    each field is looked up by name. They are written in beam order anyway, so this
    reads alongside the class declaration.
    """
    source = source_parameters()
    ref_p, ref_r = source['position'], source['orientation']

    guides, ref_p, ref_r = guide_parameters(ref_p, ref_r)
    chopper, ref_p, ref_r = chopper_parameters(ref_p, ref_r)
    jaw, ref_p, ref_r = jaw_parameters(ref_p, ref_r)
    monitor, ref_p, ref_r = monitor_parameters(ref_p, ref_r)

    return {
        'source': source,
        'guides': guides,
        'chopper': chopper,
        'jaw': jaw,
        'monitor': monitor,
        'sample_origin': {
            'name': 'sample_origin',
            'position': at_relative(ref_p, ref_r, 1000 * mm * z),
            'orientation': ref_r,
        },
    }
# --8<-- [end:chain]
