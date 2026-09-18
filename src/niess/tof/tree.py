"""Chopper specs for `tof`, read off the tree.

`niess.tof` builds these from what `niess.chopcalc` extracted, which is C *text* --
`chopcalc` emits text on purpose, so a band recomputes when a chopper speed changes at
run time. `tof` configures one specific machine and needs numbers, so it parses the text
back: `ParameterValues.evaluate_text`, and `_fold` underneath it, which exists to work
around an mccode-antlr trap where identifiers become `McCodeParameter` while `Expr.evaluate`
substitutes plain `sympy.Symbol` and the substitution silently does nothing.

Reading the tree there is no text to parse. A disc's speed and delay are quantities on
the disc, and a run-time override is a value for the knob it declared -- which the disc
also names.
"""
from __future__ import annotations

from .mapping import ChopperSpec, spec_from_windows


def chopper_specs(instrument, values: dict | None = None, origin: float = 0.0,
                  skip=(), path_lengths=None) -> tuple[ChopperSpec, ...]:
    """Every disc in ``instrument``, as ``tof`` wants it.

    ``values`` overrides a knob by name -- ``{'chopperspeed': 20}`` -- which is what
    running the same instrument at a different speed means. The disc names its knobs, so
    the override needs no convention repeated here.

    ``origin`` is where the ``tof.Source`` these are paired with sits, and it belongs to
    the model rather than to the instrument: an ESS source in ``tof`` carries its own
    0.05 m facility offset, while the niess moderator is at the instrument origin. Pass
    ``source.distance`` to have the two agree.
    """
    from ..chopcalc.tree import train_from_instrument
    from ..components.chopper import DiscChopper
    from ..walk import visits

    values = dict(values or {})
    train = train_from_instrument(instrument, skip=skip, path_lengths=path_lengths)
    paths = {entry.name: float(entry.path) for entry in train.choppers}

    specs = []
    for visit in visits(instrument):
        disc = visit.obj
        if not isinstance(disc, DiscChopper) or visit.name not in paths:
            continue
        speed = values.get(disc.speed_parameter(),
                           float(disc.speed.to(unit='Hz').value))
        delay = values.get(disc.delay_parameter(),
                           float(disc.delay.to(unit='s').value))
        beam = float(disc.beam_angle.to(unit='deg').value)
        windows = tuple((beam - closing, beam - opening)
                        for opening, closing in disc.slits())
        specs.append(spec_from_windows(
            name=visit.name, windows=windows, delay=float(delay), speed=float(speed),
            distance=origin + paths[visit.name]))
    return tuple(sorted(specs, key=lambda spec: spec.distance))
