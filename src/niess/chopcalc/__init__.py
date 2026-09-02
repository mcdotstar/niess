"""Only simulate the wavelengths a chopper train can actually pass.

A source samples uniformly across the band it is given, and a chopper train throws most of
that away. Narrowing the source's own ``Lmin``/``Lmax`` to the band the train passes is
free simulation speed: every neutron that would have been absorbed at the first chopper is
never created.

The band cannot be worked out when the instrument is built, because it depends on chopper
speeds and delays that are run-time parameters. So this emits C instead, calling
chopper-lib from the instrument's INITIALIZE -- which McCode runs before every component's
own initialisation, so the source reads the narrowed values.

    primary.to_mccode(assembler)
    narrow_source_wavelengths(assembler)
"""
from __future__ import annotations

import logging

import dataclasses
import re

from mccode_antlr.assembler import Assembler
from mccode_antlr.instr import Instr

from .emit import (CHOPPER_LIB_REGISTRY, already_emitted, declare_block,
                   export_declare_block, finalize_block, include_present,
                   initialize_block)
from .model import ChopperEntry, ChopperTrain, Exclusion, Export, SourceEntry
from .paths import ChopcalcError
from .train import train_from_instrument

C_IDENTIFIER = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')

logger = logging.getLogger(__name__)

__all__ = [
    'ChopcalcError',
    'ChopperEntry',
    'ChopperTrain',
    'Exclusion',
    'Export',
    'SourceEntry',
    'narrow_source_wavelengths',
    'train_from_instrument',
]


def narrow_source_wavelengths(
        obj: Assembler | Instr,
        chopper_train: ChopperTrain,
        *,
        export_choppers: str | None = None,
        export_chopper_count: str | None = None,
        registry: str = CHOPPER_LIB_REGISTRY,
        strict: bool = False,
) -> ChopperTrain | None:
    """Restrict the source's wavelength band to what the chopper train passes.

    Call it once the instrument is complete -- after every section and every hand-added
    component, before writing the instrument out.

    Parameters
    ----------
    obj:
        An Instr or **top-level** assembler. A child from ``assembler.included(...)``
        merges into its parent only when the block exits,
        so its choppers are not visible yet.
    chopper_train:
        The train to narrow to, from `train_from_instrument`. Required: this function is
        emission, and finding a train is not something it can do from an assembled
        instrument any more: reading one back was a second route, and the demotion
        removed it. Anything that shaped the search -- which source, which
        choppers to skip, what flight paths, how late the source still emits -- is an
        argument to `train_from_instrument` now, where the searching happens.
    export_choppers:
        Publish the train under this name as well, as a ``multi_chopper_parameters *`` in
        DECLARE, for a component that takes the train as a parameter. Allocated in
        INITIALIZE and freed in FINALLY. Without it the train is built, used and thrown
        away inside one braced block in INITIALIZE, which is what keeps its own names from
        colliding with anything else there.
    export_chopper_count:
        The ``int`` in DECLARE holding how many rows were published. Defaults to
        ``f'{export_choppers}_count'``.
    registry:
        The source of library functions called by the emitted C code.
    strict:
        Raise :class:`ChopcalcError` instead of warning and doing nothing. Worth passing
        alongside ``export_choppers``: a component that reads the train needs it to exist,
        and the default is to warn and emit nothing.

    Returns
    -------
    The train that was used, or ``None`` when nothing could be narrowed.
    """
    from ..assembler import ensure_registry
    if isinstance(obj, Assembler):
        if getattr(obj, 'parent', None) is not None:
            raise ChopcalcError(
                'narrow_source_wavelengths needs the top-level Assembler, after every '
                'section has been added. A section\'s child Assembler is merged into its '
                'parent only on leaving the included() block, so its components -- and '
                'every later section\'s -- are not visible yet.'
            )
        instrument = obj.instrument
    else:
        # An Instr's component instances have their .source field filled with their
        # name when they are %include'd in another Instr; so an Instr that has
        # a component instance _without_ a source property (inst.source is None)
        # *has not* been included. But an Instr without any non-included component
        # instances _may_ consist of _only_ %include statements, so this check would
        # not be reliable.
        # Instead, we trust that the user knows what they are doing.
        instrument = obj

    if already_emitted(instrument):
        return _refuse('this instrument has already been narrowed; calling '
                       'narrow_source_wavelengths twice would apply two bands', strict)

    try:
        export = _export_names(instrument, export_choppers, export_chopper_count)
    except ChopcalcError as error:
        return _refuse(str(error), strict)
    chopper_train = dataclasses.replace(chopper_train, export=export)

    for exclusion in chopper_train.excluded:
        logger.warning('niess.chopcalc: leaving out %s -- %s',
                       ', '.join(exclusion.members), exclusion.reason)

    if not chopper_train.choppers:
        why = '; '.join(f'{e.name}: {e.reason}' for e in chopper_train.excluded)
        return _refuse(
            f'no chopper reached the calculation, so there is nothing to narrow'
            f'{" -- " + why if why else ""}', strict)

    ensure_registry(instrument, registry)
    if not include_present(instrument):
        instrument.DECLARE(declare_block())
    if export is not None:
        instrument.DECLARE(export_declare_block(export))
    instrument.INITIALIZE(initialize_block(chopper_train))
    if export is not None:
        instrument.FINALLY(finalize_block(export))
    logger.info(
        'niess.chopcalc: %d chopper(s) narrowing %s/%s of source %r',
        len(chopper_train.choppers), chopper_train.source.lambda_min, chopper_train.source.lambda_max,
        chopper_train.source.name,
    )
    return chopper_train


def _export_names(instrument, choppers: str | None, count: str | None) -> Export | None:
    """Check the names a caller wants the train published under.

    They become file-scope C, so a name that is not an identifier, or is already taken by
    an instrument parameter, is a compile error in generated code -- which is a much worse
    place to find out than here.
    """
    if choppers is None:
        if count is not None:
            raise ChopcalcError(
                'export_chopper_count names the count of a published train, so it needs '
                'export_choppers to say what to publish'
            )
        return None
    count = count if count is not None else f'{choppers}_count'
    for name, argument in ((choppers, 'export_choppers'), (count, 'export_chopper_count')):
        if not C_IDENTIFIER.match(name):
            raise ChopcalcError(
                f'{argument}={name!r} is not a C identifier, and it is declared as one'
            )
        if name.startswith('chopcalc_'):
            raise ChopcalcError(
                f'{argument}={name!r} starts with chopcalc_, which is reserved for the '
                f'locals this generates; pick another name'
            )
        if instrument.get_parameter(name) is not None:
            raise ChopcalcError(
                f'{argument}={name!r} is already an instrument parameter, so declaring it '
                f'again would not compile'
            )
    if choppers == count:
        raise ChopcalcError(
            f'export_choppers and export_chopper_count are both {choppers!r}; they are '
            f'two different variables'
        )
    return Export(choppers=choppers, count=count)


def _refuse(message: str, strict: bool) -> None:
    """Emitting nothing is always safe -- the instrument samples the band it was given."""
    if strict:
        raise ChopcalcError(message)
    logger.warning('niess.chopcalc: %s', message)
    return None
