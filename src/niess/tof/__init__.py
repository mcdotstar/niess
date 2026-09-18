"""Fly neutrons through a chopper cascade, from a niess instrument.

``tof`` (from the scipp developers) is a lightweight straight-line Monte Carlo for chopper
cascade diagrams. It wants the same description of a chopper train `niess.chopcalc`
extracts, with one difference: chopcalc emits parameter *names* so a band recomputes at
run time, while ``tof`` configures one specific machine and needs numbers.

Reading the tree, they already are numbers -- a disc's speed and delay are quantities on
the disc:

    from niess.instrument import Instrument, Mount
    from niess.teaching import Primary
    from niess.tof import to_tof_model

    teaching = Instrument(name='teaching', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration()),
    ))

    setup = to_tof_model(teaching)
    setup                      # in a notebook: what it used, and what you may override
    setup.model.run().plot()

Modelling an instrument niess did *not* build meant reading an emitted one and parsing
those numbers back out of the C. That route is gone: niess models niess instruments.

Install with ``pip install 'niess[tof]'``.
"""
from __future__ import annotations

from .mapping import ChopperSpec, delay_to_phase, spec_from_windows
from .model import chopper_specs, to_tof_model
from .parameters import Use, as_declared
from .setup import TofSetup

__all__ = [
    'ChopperSpec',
    'TofSetup',
    'Use',
    'as_declared',
    'chopper_specs',
    'delay_to_phase',
    'spec_from_windows',
    'to_tof_model',
]
