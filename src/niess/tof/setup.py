"""The `tof` package itself, and the result both routes hand back.

`TofSetup` is what a notebook actually looks at -- the model, plus which knobs went into
it and at what value -- and it is the same answer whether the instrument was read from
the tree or from an emitted file. `_tof` is the one place the optional dependency is
imported, so a missing extra says so once and in words.

Note that ``import tof`` inside this package is an absolute import and reaches the scipp
package, not ``niess.tof``; every use goes through `_tof` so it is never in doubt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .mapping import ChopperSpec
from .parameters import Use


def _tof():
    """The scipp ``tof`` package, imported when it is actually needed.

    Absolute, so this reaches the real ``tof`` and not ``niess.tof``.
    """
    try:
        import tof
    except ImportError as error:  # pragma: no cover - depends on the environment
        raise ImportError(
            "niess.tof needs the 'tof' package: pip install 'niess[tof]'"
        ) from error
    return tof

@dataclass(frozen=True)
class TofSetup:
    """A ready-to-run ``tof.Model``, and what went into it.

    Displaying this in a notebook answers "what do I need to provide?" -- which, for an
    instrument niess built, is usually nothing: every chopper knob is declared with the
    calibration's own value as its default. The knobs are listed anyway, because knowing
    which ones exist is the point of asking.
    """

    model: Any
    source: Any
    choppers: tuple[ChopperSpec, ...]
    detectors: tuple[str, ...]
    parameters: tuple[Use, ...]
    excluded: tuple[Any, ...] = ()
    notes: tuple[str, ...] = ()
    _rebuild: Any = field(default=None, repr=False, compare=False)

    def with_values(self, **overrides) -> 'TofSetup':
        """The same instrument again, with these instrument parameters replaced."""
        if self._rebuild is None:
            raise RuntimeError('this setup was not built from an instrument')
        return self._rebuild(overrides)

    def __repr__(self) -> str:
        lines = [f'TofSetup: {len(self.choppers)} chopper(s), '
                 f'{len(self.detectors)} detector(s)']
        for spec in self.choppers:
            sense = 'anticlockwise' if spec.anticlockwise else 'clockwise'
            lines.append(f'  chopper  {spec.name:28s} {spec.frequency:8.3f} Hz {sense:14s}'
                         f' {len(spec.open)} opening(s) at {spec.distance:8.4f} m')
        for name in self.detectors:
            lines.append(f'  detector {name}')
        if self.parameters:
            lines.append('')
            lines.append('  parameters used (override with with_values(...)):')
            for use in self.parameters:
                unit = f' {use.unit}' if use.unit else ''
                where = 'given' if use.overridden else 'default'
                lines.append(f'    {use.name:28s} = {use.value!r}{unit}  ({where})'
                             f'  <- {", ".join(use.used_by)}')
            if not any(use.overridden for use in self.parameters):
                lines.append('  nothing has to be provided; every value came from the '
                             'instrument itself.')
        for exclusion in self.excluded:
            lines.append(f'  left out: {exclusion.name} -- {exclusion.reason}')
        for note in self.notes:
            lines.append(f'  note: {note}')
        return '\n'.join(lines)

    def _repr_markdown_(self) -> str:
        rows = ['| parameter | value | unit | from | read by |',
                '| --- | --- | --- | --- | --- |']
        for use in self.parameters:
            rows.append(f'| `{use.name}` | {use.value!r} | {use.unit or ""} | '
                        f'{"given" if use.overridden else "instrument default"} | '
                        f'{", ".join(f"`{u}`" for u in use.used_by)} |')
        head = (f'**{len(self.choppers)} chopper(s), {len(self.detectors)} detector(s)** '
                f'— ready to `run()`.\n\n')
        if not self.parameters:
            return head + 'No instrument parameters were needed.'
        tail = ('\n\nNothing has to be provided; every value came from the instrument '
                'itself. Override any of them with `with_values(...)`.'
                if not any(u.overridden for u in self.parameters) else '')
        return head + '\n'.join(rows) + tail

def _facility_for(instrument, tof) -> str:
    """The pulse profile that matches this instrument, or the generic ESS one."""
    candidate = f'ess-{instrument.name}'.lower()
    library = getattr(tof.facilities, 'source_library', {})
    return candidate if candidate in library else 'ess'
