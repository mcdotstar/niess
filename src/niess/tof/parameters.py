"""Instrument parameters as numbers, and a record of which ones were used.

``niess.chopcalc`` emits parameter *names* on purpose, so a band recomputes at run time.
``tof`` configures one specific machine, so it needs values. Everything here is about
getting from one to the other, and about being able to tell a notebook user afterwards
which knobs the model actually turned on.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..dispatch import expr_float


@dataclass(frozen=True)
class Use:
    """One instrument parameter the model depended on."""

    name: str
    value: float
    default: float | None
    unit: str | None
    overridden: bool
    """Whether the caller supplied it, rather than the instrument's own default."""
    used_by: tuple[str, ...]
    """Where it was read, as ``component.parameter``, for the report."""


def instrument_defaults(instrument) -> dict[str, object]:
    """Every DEFINE INSTRUMENT parameter that has a value, by name.

    niess writes a chopper's speed and delay with the calibration's own numbers as the
    defaults, so an instrument it built is usually complete on its own -- which is why the
    report below can normally say that nothing needs supplying.
    """
    known = {}
    for parameter in instrument.parameters:
        value = parameter.value
        if value is None or not getattr(value, 'has_value', False):
            continue
        known[parameter.name] = value
    return known


def instrument_units(instrument) -> dict[str, str | None]:
    """Parameter units, unquoted -- a DEFINE line carries them as `name/"Hz" = 14`."""
    return {p.name: (p.unit or '').strip().strip('"') or None
            for p in instrument.parameters}


def as_declared(name: str, value, unit: str | None) -> float:
    """A supplied value as a plain number, in the unit whatever reads it declares.

    A chopper speed calculated elsewhere arrives as a scipp scalar carrying its own unit
    -- and a calculator is as entitled to hand back a period in milliseconds or a speed in
    rpm as it is to match what the instrument happens to say. The thing being set knows
    what unit it wants, so convert rather than making the caller strip the unit and hope
    the two agree.

    ``unit`` of ``None`` means nothing declared one, so there is nothing to convert to and
    the number is taken as it comes. Shared with the tree-reading route, which knows the
    unit from the disc rather than from a DEFINE line, so that a value carrying its unit
    is accepted the same way whichever way the instrument was read.
    """
    if not hasattr(value, 'unit'):
        return float(value)
    if unit is None:
        return float(value.value)
    try:
        return float(value.to(unit=unit, dtype='float64').value)
    except Exception as error:
        raise ValueError(
            f'{name} is declared in {unit!r} and {value.unit} does not convert to it'
        ) from error


class ParameterValues:
    """The values to evaluate expressions against, and a note of what got used."""

    def __init__(self, instrument, overrides: dict[str, float] | None = None):
        self.instrument = instrument
        self.defaults = instrument_defaults(instrument)
        self.units = instrument_units(instrument)
        overrides = {} if overrides is None else dict(overrides)
        unknown = set(overrides) - {p.name for p in instrument.parameters}
        if unknown:
            raise ValueError(
                f'{sorted(unknown)} are not instrument parameters of '
                f'{instrument.name!r}; it has {sorted(p.name for p in instrument.parameters)}'
            )
        self.overrides = {name: self._as_declared(name, value)
                          for name, value in overrides.items()}
        self.values = {**self.defaults, **self.overrides}
        self._uses: dict[str, set[str]] = {}

    def evaluate(self, expression, *, used_by: str | None = None) -> float | None:
        """An expression as a number, or ``None`` when it does not fold to one."""
        if expression is None:
            return None
        try:
            return float(expression)
        except (TypeError, ValueError):
            pass

        for name in self.values:
            if _depends_on(expression, name):
                self._uses.setdefault(name, set()).add(used_by or '?')

        folded = _fold(expression, self.values)
        if folded is None:
            return None
        try:
            return expr_float(folded)
        except (TypeError, ValueError):
            return None

    def _as_declared(self, name: str, value):
        """An override in the unit this instrument declares for it."""
        return as_declared(name, value, self.units.get(name))

    def evaluate_text(self, text, *, used_by: str | None = None) -> float | None:
        """A `chopcalc` field -- C text naming instrument parameters -- as a number.

        chopcalc writes C so a band recomputes at run time, and everything it writes
        happens to parse as a McCode expression, the conditional it emits for a run-time
        phase included. So the train it extracts can be reused whole rather than the
        instrument walked a second time.
        """
        from mccode_antlr.common.expression import Expr

        if text is None:
            return None
        try:
            return float(text)
        except (TypeError, ValueError):
            pass
        try:
            expression = Expr.parse(str(text))
        except Exception:
            return None
        return self.evaluate(expression, used_by=used_by)

    def number(self, instance, name: str, *, default: float | None = None):
        """A component parameter as a number, recording what it depended on."""
        parameter = instance.get_parameter(name)
        if parameter is None:
            return default
        value = self.evaluate(parameter.value, used_by=f'{instance.name}.{name}')
        return default if value is None else value

    def uses(self) -> tuple[Use, ...]:
        """What the model read, in the order the instrument declares it."""
        found = []
        for parameter in self.instrument.parameters:
            if parameter.name not in self._uses:
                continue
            value = self.values.get(parameter.name)
            found.append(Use(
                name=parameter.name,
                value=_as_float(value),
                default=_as_float(self.defaults.get(parameter.name)),
                unit=self.units.get(parameter.name),
                overridden=parameter.name in self.overrides,
                used_by=tuple(sorted(self._uses[parameter.name])),
            ))
        return tuple(found)


def _as_float(value):
    if value is None:
        return None
    try:
        return expr_float(value)
    except (TypeError, ValueError):
        return None


def _depends_on(expression, name: str) -> bool:
    try:
        return bool(expression.depends_on(name))
    except (AttributeError, TypeError):
        return False


def _fold(expression, values):
    """Substitute and simplify, working around a parameter-flagged expression.

    Once an identifier has been verified as an instrument parameter it becomes a
    ``McCodeParameter``, a ``sympy.Symbol`` *subclass*, while ``Expr.evaluate`` builds its
    substitution map from plain ``sympy.Symbol``. The two do not match, so the
    substitution silently does nothing and the expression comes back unevaluated:

        >>> e = Expr.parse('fabs(spd)/2'); e.verify_parameters(['spd'])
        >>> e.evaluate({'spd': -14.0})
        (1.0/2.0)*fabs(spd)

    Printing and re-parsing normalises it, because ``McCodeParameter`` prints as the plain
    name. Try the direct route first and only pay for the round trip when it was needed.
    """
    from mccode_antlr.common.expression import Expr

    try:
        folded = expression.evaluate(values)
    except Exception:
        folded = None
    if folded is not None and getattr(folded, 'is_constant', False):
        return folded
    try:
        return Expr.parse(str(expression)).evaluate(values)
    except Exception:
        return folded
