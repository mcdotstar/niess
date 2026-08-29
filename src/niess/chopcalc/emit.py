"""Turn a discovered chopper train into C. Nothing here reads the instrument."""
from __future__ import annotations

from textwrap import indent

from .model import ChopperTrain, Export

CHOPPER_LIB_REGISTRY = 'mcdotstar/mcstas-chopper-lib@v3.0.0'
CHOPPER_LIB_MINIMUM_VERSION = 30000
INCLUDE_MARKER = '%include "chopper-lib"'
ARRAY_MARKER = 'chopcalc_choppers'
INDEX_MARKER = 'chopcalc_i'
OUT_OF_MEMORY = 'niess.chopcalc: out of memory building the chopper train'

DECLARE_TEXT = f'''
/* niess.chopcalc: chopper-lib, for narrowing the source wavelength band */
{INCLUDE_MARKER}
#if !defined(CHOPPER_LIB_VERSION) || CHOPPER_LIB_VERSION < {CHOPPER_LIB_MINIMUM_VERSION}
#error "niess.chopcalc describes discs by their openings; chopper-lib 3.0.0 or newer is required"
#endif
'''


def declare_text() -> str:
    """The library include, and the guard that stops an older one being used silently.

    Nothing here changes size or layout when chopper-lib's meaning changes -- the second
    field went from a phase in degrees to a delay in seconds at 2.0.0, and a window angle
    started being placed with the signed speed at 3.0.0 -- so without the guard an older
    library compiles cleanly and computes a different band.
    """
    return DECLARE_TEXT


def export_declare_text(export: Export) -> str:
    """File-scope storage for a train a component reads.

    Declared here and filled in INITIALIZE rather than initialised in place: a row names
    instrument parameters, which are not constant expressions, so it cannot be a static
    initialiser.
    """
    return f"""
/* niess.chopcalc: the chopper train, for components that take it as a parameter.
 * INITIALIZE hands over the train it built and FINALLY releases it, so it is valid for
 * the whole run -- which it is not otherwise, being freed as INITIALIZE leaves. Pass
 * (double *) {export.choppers} to a component whose parameter is declared that way.
 */
multi_chopper_parameters * {export.choppers} = NULL;
int {export.count} = 0;
"""


def initialize_text(train: ChopperTrain) -> str:
    """The whole calculation, as one braced compound statement.

    Braced so ``chopcalc_*`` cannot collide with anything else in INITIALIZE. The rows are
    filled at run time rather than statically initialised, which is what lets one name an
    instrument parameter.

    The train is built on the heap whether or not anything else will read it. That costs
    one allocation per disc and buys a single construction path: handing the train to a
    component is then a pointer assignment rather than a copy, and the release is the same
    few lines either way -- emitted at the end of this block when nobody else wants it, and
    in FINALLY when somebody does.
    """
    source = train.source
    count = len(train.choppers)

    # A row carries a pointer to its openings, so each gets an array of its own, allocated
    # where the row is written. Checking them all at once afterwards keeps the table above
    # readable and the boilerplate the same size however many discs there are.
    rows = '\n'.join(
        f'  {ARRAY_MARKER}[{i}] = (multi_chopper_parameters){{'
        f'{c.speed}, {c.delay}, {len(c.windows)},\n'
        f'    (chopper_window *) calloc({len(c.windows)}, sizeof(chopper_window)),'
        f' {c.path}}};'
        f' /* {c.name}, {len(c.windows)} opening{"" if len(c.windows) == 1 else "s"}'
        f'{"" if c.note is None else " -- " + c.note} */'
        for i, c in enumerate(train.choppers)
    )
    # written out index by index: the values differ per opening, so a loop would need a
    # table to read from, and the table would be this
    openings = '\n'.join(
        f'  {ARRAY_MARKER}[{i}].windows[{w}] = (chopper_window){{{lo}, {hi}}};'
        for i, c in enumerate(train.choppers)
        for w, (lo, hi) in enumerate(c.windows)
    )

    if train.export is None:
        handover = f'''
  /* nothing else reads the train, so give it back before leaving */
{_release(ARRAY_MARKER, str(count))}'''
    else:
        handover = f'''
  /* hand the train over; FINALLY releases it */
  {train.export.choppers} = {ARRAY_MARKER};
  {train.export.count} = {count};'''

    notes = [
        f'{len(train.choppers)} chopper{"" if len(train.choppers) == 1 else "s"} '
        f'considered, path lengths walked along the beam from {source.name!r}.',
    ]
    if train.export is not None:
        notes.append(f'Also published as {train.export.choppers} / {train.export.count}, '
                     f'for a component that reads the train.')
    for chopper in (c for c in train.choppers if c.note):
        notes.append(f'{chopper.name}: {chopper.note}.')
    for exclusion in train.excluded:
        notes.append(f'{exclusion.name}: left out, {exclusion.reason}.')

    body = f'''
/* niess.chopcalc: narrow {source.lambda_min}/{source.lambda_max} to the band the chopper
 * train can pass, so the source only samples wavelengths that can reach the sample.
 * Instrument INITIALIZE runs before every _setpos and every component _initialize, so
 * {source.name!r} reads the narrowed values.
{indent(chr(10).join(" * " + n for n in notes), "")}
 */
{{
  multi_chopper_parameters * {ARRAY_MARKER} = (multi_chopper_parameters *) calloc(
    {count}, sizeof(multi_chopper_parameters));
  if ({ARRAY_MARKER} == NULL) {{
    printf("{OUT_OF_MEMORY}\\n");
    exit(-1);
  }}
{rows}
  for (int {INDEX_MARKER} = 0; {INDEX_MARKER} < {count}; ++{INDEX_MARKER}) {{
    if ({ARRAY_MARKER}[{INDEX_MARKER}].windows == NULL) {{
      printf("{OUT_OF_MEMORY}\\n");
      exit(-1);
    }}
  }}
{openings}
  double chopcalc_latest = {source.latest_emission}; /* {source.latest_emission_note}, s */
  double chopcalc_min = {source.lambda_min}, chopcalc_max = {source.lambda_max};
  unsigned chopcalc_bands = multi_chopper_wavelength_limits(
    &{source.lambda_min}, &{source.lambda_max},
    {count}, {ARRAY_MARKER},
    chopcalc_min, chopcalc_max, chopcalc_latest);
  if (chopcalc_bands == 0 || !({source.lambda_max} > {source.lambda_min})
      || {source.lambda_min} <= 0) {{
    /* multi_chopper_wavelength_limits leaves its outputs alone when it finds nothing; putting
     * the band back makes that a property of this instrument rather than of whichever
     * library version was resolved. It also keeps a degenerate band away from
     * ESS_butterfly, whose own INITIALIZE exits when Lmin >= Lmax. */
    {source.lambda_min} = chopcalc_min;
    {source.lambda_max} = chopcalc_max;
    MPI_MASTER(printf(
      "niess.chopcalc: no usable band between %g and %g AA -- sampling unchanged.\\n"
      "niess.chopcalc: check the chopper speeds and delays; a delay is a time in "
      "seconds, and the sign of a speed sets the direction of rotation.\\n",
      chopcalc_min, chopcalc_max););
  }} else {{
    if (chopcalc_bands > 1) {{
      MPI_MASTER(printf(
        "niess.chopcalc: %u separate bands between %g and %g AA; their envelope is "
        "used, so wavelengths they block are still sampled.\\n",
        chopcalc_bands, chopcalc_min, chopcalc_max););
    }}
    MPI_MASTER(printf("niess.chopcalc: sampling %g to %g AA instead of %g to %g AA.\\n",
      {source.lambda_min}, {source.lambda_max}, chopcalc_min, chopcalc_max););
  }}
{handover}
}}
'''
    return body


def _release(name: str, count: str) -> str:
    """Give back a train built by :func:`initialize_text`.

    Each row owns its openings, so those go first: freeing the row array alone loses every
    window array with it. Emitted at the end of INITIALIZE when nothing else reads the
    train, and in FINALLY when something does -- the same lines, in one place or the other.
    """
    return f'''  for (int {INDEX_MARKER} = 0; {INDEX_MARKER} < {count}; ++{INDEX_MARKER}) {{
    if ({name}[{INDEX_MARKER}].windows != NULL) free({name}[{INDEX_MARKER}].windows);
  }}
  free({name});'''


def finalize_text(export: Export) -> str:
    """Release a train INITIALIZE handed over."""
    return f'''
/* niess.chopcalc: release the published chopper train */
if ({export.choppers} != NULL) {{
{_release(export.choppers, export.count)}
  {export.choppers} = NULL;
  {export.count} = 0;
}}
'''


def already_emitted(instrument) -> bool:
    """Has a previous call already narrowed this instrument?"""
    return any(ARRAY_MARKER in str(block) for block in instrument.initialize)


def include_present(instrument) -> bool:
    return any(INCLUDE_MARKER in str(block) for block in instrument.declare)


def _block(text):
    from mccode_antlr.common import RawC
    return RawC('niess/chopcalc/emit.py', 0, text)


def declare_block():
    return _block(declare_text())

def export_declare_block(export: Export):
    return _block(export_declare_text(export))


def initialize_block(train: ChopperTrain):
    return _block(initialize_text(train))


def finalize_block(export: Export):
    return _block(finalize_text(export))
