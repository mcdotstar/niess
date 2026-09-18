"""Which niess class, if any, a McStas component becomes.

A recipe takes one `Instance` and the instrument's constant folder, and returns the niess
class to build and the calibration keys it needs -- or `None`.

**`None` means "I cannot map this confidently", and the component becomes an `Opaque`.**
That is the important half of the contract. A recipe that guesses produces a module which
looks more finished than it is and quietly misstates the instrument; an `Opaque` says
plainly that niess does not model this yet, and lands on the to-do list the conversion
prints. Returning `None` is a success.

Only map where the **McStas type determines the niess class**. The table in
`docs/reference/components.md` reads as though it inverts, and mostly it does not:

- Every niess monitor emits `Frame_monitor`, so `Frame_monitor` cannot be inverted at all.
- `docs/how-to/translate-an-instr.md` maps `TOF_monitor` to `FissionChamber`. That is a
  judgement about *that* instrument -- a fission chamber is a specific device, not what
  every `TOF_monitor` is -- and a general tool must not make it.

So this table is deliberately much shorter than the component reference, and the honest
fraction of a real instrument it covers is small: 8 of 50 components for ESS_IN5_reprate.
Growing it is the way to make conversions better, one well-understood component at a time.

Adding one
----------

Write a function, register it in `RECIPES`, and add a case to
`tests/test_scaffold_recipes.py`. `niess.scaffold.verify` will tell you if the placement
came out wrong, which is the failure that matters and the reason a recipe as delicate as
`disk_chopper`'s is safe to attempt at all.
"""
from __future__ import annotations

from typing import Any, Callable

from scipp import scalar

from ..components import (
    Aperture, Component, DiscChopper, ESSource, Jaw, Slit, StraightGuide, TaperedGuide,
)

#: `(niess class, calibration keys beyond name/position/orientation)`, or `None`.
Recipe = Callable[[Any, Callable], "tuple[type, dict] | None"]


def _setting(instance, name: str, fold, default=None):
    """One component parameter as a number, or `default` if it was never given.

    Reads the instance first and the component *definition* second, so a parameter left
    at its `.comp` default is still found -- `Instance.get_parameter` already does that
    fallback. A `.comp` parameter with no default at all reads as `UNSET`, which is
    `default` here rather than a number.
    """
    parameter = instance.get_parameter(name)
    if parameter is None or parameter.value is None:
        return default
    if parameter.value.is_constant and not parameter.value.has_value:
        return default
    try:
        return fold(parameter.value, f'{instance.name}.{name}')
    except (ValueError, TypeError, NotImplementedError):
        return default


def _is_runtime(instance, name: str) -> bool:
    """Whether *this instance* drives a component parameter from an instrument parameter.

    Deliberately not `Instance.get_parameter`, which falls back to the `.comp`
    definition: the question is what the instrument author wrote on this line, and a
    definition default is not that.
    """
    for parameter in instance.parameters:
        if parameter.name == name:
            value = parameter.value
            return value is not None and not value.is_constant
    return False


def arm(instance, fold):
    """A bare coordinate frame. `Component` emits exactly this."""
    return Component, {}


def ess_butterfly(instance, fold):
    sector = instance.get_parameter('sector')
    beamline = _setting(instance, 'beamline', fold, 1)
    cold = _setting(instance, 'cold_frac', fold, 0.5)
    height = _setting(instance, 'yheight', fold, 0.03)
    calibration = {
        'sector': str(sector.value).strip('"') if sector is not None else 'W',
        'beamline': int(beamline),
        'height': scalar(float(height), unit='m'),
        'cold_fraction': float(cold),
    }
    # `ESS_butterfly` reads zero as "no focusing", and so does leaving the key out.
    for key, name in (('focus_distance', 'dist'),
                      ('focus_width', 'focus_xw'),
                      ('focus_height', 'focus_yh')):
        value = _setting(instance, name, fold)
        if value:
            calibration[key] = scalar(float(value), unit='m')
    return ESSource, calibration


def _guide_m_values(instance, fold):
    """`m` as one number, or the four faces where they differ.

    `Guide_gravity` reads a **negative** per-face m-value as "use `m`", which is also its
    default -- so a face is only really set when it is positive. Reading -1 as a coating
    would give every converted guide four mirrors that reflect nothing.
    """
    faces = {key: _setting(instance, key, fold, -1.0)
             for key in ('mleft', 'mright', 'mtop', 'mbottom')}
    if any(value is not None and value > 0 for value in faces.values()):
        return {'left': faces['mleft'], 'right': faces['mright'],
                'top': faces['mtop'], 'bottom': faces['mbottom']}
    return {'m': float(_setting(instance, 'm', fold, 0.0) or 0.0)}


def guide_gravity(instance, fold):
    """`Guide_gravity` is straight or tapered, and the parameters say which."""
    length = _setting(instance, 'l', fold)
    w1 = _setting(instance, 'w1', fold)
    h1 = _setting(instance, 'h1', fold)
    if length is None or w1 is None or h1 is None:
        return None
    # McStas reads a zero exit dimension as "same as the entrance"
    w2 = _setting(instance, 'w2', fold, 0.0) or w1
    h2 = _setting(instance, 'h2', fold, 0.0) or h1

    calibration = {'length': scalar(float(length), unit='m')}
    calibration.update(_guide_m_values(instance, fold))

    if abs(w1 - w2) < 1e-12 and abs(h1 - h2) < 1e-12:
        calibration['width'] = scalar(float(w1), unit='m')
        calibration['height'] = scalar(float(h1), unit='m')
        return StraightGuide, calibration

    calibration['in_width'] = scalar(float(w1), unit='m')
    calibration['out_width'] = scalar(float(w2), unit='m')
    calibration['in_height'] = scalar(float(h1), unit='m')
    calibration['out_height'] = scalar(float(h2), unit='m')
    return TaperedGuide, calibration


def slit(instance, fold):
    """`Slit` is a fixed `Aperture`, or a run-time `Jaw`/`Slit` if its edges are driven.

    niess models a driven edge as an instrument parameter the class declares itself, so
    which class this is depends on whether the original's edges were run-time.
    """
    horizontal = _is_runtime(instance, 'xmin') or _is_runtime(instance, 'xmax')
    vertical = _is_runtime(instance, 'ymin') or _is_runtime(instance, 'ymax')

    width = _setting(instance, 'xwidth', fold)
    height = _setting(instance, 'yheight', fold)
    if width is None:
        xmin, xmax = _setting(instance, 'xmin', fold), _setting(instance, 'xmax', fold)
        width = None if xmin is None or xmax is None else xmax - xmin
    if height is None:
        ymin, ymax = _setting(instance, 'ymin', fold), _setting(instance, 'ymax', fold)
        height = None if ymin is None or ymax is None else ymax - ymin
    if width is None or height is None:
        # a radius-defined slit, which niess has no class for
        return None

    calibration = {'width': scalar(float(width), unit='m'),
                   'height': scalar(float(height), unit='m')}
    if vertical:
        return Slit, calibration
    if horizontal:
        return Jaw, calibration
    return Aperture, calibration


def disk_chopper(instance, fold):
    """`DiskChopper` -> `DiscChopper`, undoing McStas' placement convention.

    The trap, stated in `docs/reference/components.md`: a niess disc's `position` is its
    **spindle**, while the emitted `AT` is where the beam crosses the disc. Reading the
    `.instr`'s `AT` as the position would put the disc off the beam, where it absorbs
    everything without saying so -- which is why `DiscChopper.from_calibration` refuses a
    calibration carrying a raw `offset` rather than ignoring it.

    So the `AT` has to be walked back to the spindle. `disc_beam_offset` is the one
    formula and this negates it, exactly as `niess.teaching.parameters.chopper_parameters`
    does by hand. The two conventions line up term for term: McStas sets
    ``delta_y = radius - yheight/2`` and draws its disc *below* the component origin, and
    `disc_beam_offset` with no width and both angles zero is ``radius - height/2`` along
    +y. Hence `width=None` here -- passing a width would engage the improved reach
    calculation and place the disc somewhere McStas does not.

    `niess.scaffold.verify` is what confirms all of the above, and the reason a recipe
    this delicate is safe to attempt at all.
    """
    from scipp import array
    from ..components.chopper import disc_beam_offset

    radius = _setting(instance, 'radius', fold)
    theta = _setting(instance, 'theta_0', fold)
    frequency = _setting(instance, 'nu', fold)
    if radius is None or theta is None or frequency is None:
        return None

    nslit = int(_setting(instance, 'nslit', fold, 1) or 1)
    # McStas reads yheight=0 as "the opening reaches the centre of the disc", and
    # `disc_beam_offset` agrees: the offset is then the full radius.
    height = scalar(float(_setting(instance, 'yheight', fold, 0.0) or 0.0), unit='m')
    radius = scalar(float(radius), unit='m')

    # `nslit` identical, evenly spaced openings of angular width `theta_0`, the first
    # centred on the beam. That is all a McStas DiskChopper can describe, and with
    # zero_angle = beam_angle = 0 the beam is the zero mark, so the edges are measured
    # from where the first opening is centred.
    edges = []
    for index in range(nslit):
        centre = index * 360.0 / nslit
        edges.extend((centre - theta / 2.0, centre + theta / 2.0))

    zero_angle = scalar(0.0, unit='deg')
    beam_angle = scalar(0.0, unit='deg')

    return DiscChopper, {
        'radius': radius,
        'windows': array(values=edges, dims=['edges'], unit='deg'),
        'height': height,
        'width': None,
        'zero_angle': zero_angle,
        'beam_angle': beam_angle,
        'frequency': scalar(float(frequency), unit='Hz'),
        'delay': scalar(float(_setting(instance, 'delay', fold, 0.0) or 0.0), unit='s'),
        # the `.instr` placed the beam crossing; `position` must be the spindle
        'position_offset': -disc_beam_offset(
            radius=radius, width=None, height=height,
            zero_angle=zero_angle, beam_angle=beam_angle,
        ),
    }


#: McStas component type name -> recipe. Everything absent becomes an `Opaque`.
RECIPES: dict[str, Recipe] = {
    'Arm': arm,
    'ESS_butterfly': ess_butterfly,
    'Guide_gravity': guide_gravity,
    'Slit': slit,
    'DiskChopper': disk_chopper,
}


def recipe_for(type_name: str) -> Recipe | None:
    return RECIPES.get(type_name)
