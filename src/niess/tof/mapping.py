"""The numbers a ``tof.Chopper`` wants, from the way niess describes a disc.

Deliberately free of ``tof`` itself, so the arithmetic can be tested -- and printed --
without the optional dependency installed, and so the one place the conversion is
derived is one place to read.
"""
from __future__ import annotations

from dataclasses import dataclass


def delay_to_phase(delay: float, speed: float) -> float:
    """A disc's delay in seconds, as the phase angle in degrees ``tof`` wants.

    ``tof`` has no notion of a delay. An opening is placed by its angle and the whole disc
    is shifted by ``phase``, which ``open_close_times`` adds to every angle before dividing
    by the angular speed -- so a delay of ``d`` seconds is ``360 * |speed| * d`` degrees.

    **The sign does not flip with the direction of rotation**, which is the one thing here
    worth being suspicious of. A NeXus phase is an angle in the disc's own rotating frame,
    so its sign *does* flip: ``tof.Chopper.from_nexus`` writes ``phase = -phase`` for a
    negative rotation speed for exactly that reason. A niess delay is a *time*, and a later
    time is later whichever way the disc turns.

    Checked against ``Chopper.open_close_times`` for both directions on an asymmetric
    three-opening disc: negating this puts every opening somewhere else.
    """
    return 360.0 * abs(speed) * delay


@dataclass(frozen=True)
class ChopperSpec:
    """One ``tof.Chopper``, as plain numbers, before any ``tof`` object exists."""

    name: str
    frequency: float
    """Hz, never negative -- ``tof`` carries the direction separately."""
    anticlockwise: bool
    open: tuple[float, ...]
    """Degrees from the beam, one per opening, in ``tof``'s sense."""
    close: tuple[float, ...]
    phase: float
    """Degrees."""
    distance: float
    """Metres along the beam. ``tof`` measures from the same zero as its source, so this
    is the source's own distance plus the path walked to the disc."""

    def to_tof(self):
        """The ``tof.Chopper`` itself."""
        import scipp as sc

        from .setup import _tof

        tof = _tof()
        return tof.Chopper(
            frequency=sc.scalar(self.frequency, unit='Hz'),
            open=sc.array(dims=['cutout'], values=list(self.open), unit='deg'),
            close=sc.array(dims=['cutout'], values=list(self.close), unit='deg'),
            phase=sc.scalar(self.phase, unit='deg'),
            distance=sc.scalar(self.distance, unit='m'),
            name=self.name,
            direction=tof.AntiClockwise if self.anticlockwise else tof.Clockwise,
        )


def spec_from_windows(*, name: str, windows, delay: float, speed: float,
                      distance: float) -> ChopperSpec:
    """A spec from the windows ``niess.chopcalc`` extracts.

    Those windows are already in the frame where an edge at angle ``a`` is on the beam at
    ``delay + a / (360 * speed)`` -- that is, ``a`` is measured *from the beam towards the
    mark*, which is the opposite sense to ``tof``, where an opening at angle ``a`` is
    reached after turning through it. So the two swap sign, and a ``(minimum, maximum)``
    pair becomes ``(-maximum, -minimum)``: still increasing, which ``tof`` requires.
    """
    if speed == 0:
        raise ValueError(f'{name}: a chopper that is not turning has no phase')
    pairs = [(-float(high), -float(low)) for low, high in windows]
    return ChopperSpec(
        name=name,
        frequency=abs(float(speed)),
        anticlockwise=float(speed) > 0,
        open=tuple(low for low, _ in pairs),
        close=tuple(high for _, high in pairs),
        phase=delay_to_phase(float(delay), float(speed)),
        distance=float(distance),
    )
