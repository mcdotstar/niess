"""Turn a discovered chopper train into C. Nothing here reads the instrument."""
from __future__ import annotations

from textwrap import indent

from .model import ChopperTrain, Export

CHOPPER_LIB_REGISTRY = 'mcdotstar/mcstas-chopper-lib@v4.2.1'
#: 4.2.1, not 4.1.0, and the reason is `chopper_wavelength_limits` -- the one
#: function this module calls. It goes through `range_set_sort`, which until 4.2.1
#: "gave different answers on different platforms, which is how a chopper train's
#: admitted band came out 0.098 AA wide on Windows and 1.906 AA on Linux for the
#: same discs". The struct layout has been stable since 4.0.0, so an older library
#: links and runs -- it just answers the question wrong, and differently by host.
CHOPPER_LIB_MINIMUM_VERSION = 40201
INCLUDE_MARKER = '%include "chopper-lib"'
ARRAY_MARKER = 'chopcalc_choppers'
INDEX_MARKER = 'chopcalc_i'
OUT_OF_MEMORY = 'niess.chopcalc: out of memory building the chopper train'

DECLARE_TEXT = f'''
/* niess.chopcalc: chopper-lib, for narrowing the source wavelength band */
{INCLUDE_MARKER}
#if !defined(CHOPPER_LIB_VERSION) || CHOPPER_LIB_VERSION < {CHOPPER_LIB_MINIMUM_VERSION}
#error "niess.chopcalc narrows a band with chopper_wavelength_limits; chopper-lib 4.2.1 or newer is required"
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
chopper_parameters * {export.choppers} = NULL;
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
    rows = []
    for i, c in enumerate(train.choppers):
        row = f'  {ARRAY_MARKER}[{i}] = (chopper_parameters)' + '{'
        row += f'{c.speed}, {c.delay}, {c.beam}, {c.edge_count}, '
        row += (c.edges if isinstance(c.edges, str) else f' (double *) calloc({c.edge_count}, sizeof(double))')
        row += f', {c.path}, {c.aperture}' + '};'
        openings = c.edge_count // 2
        note = '' if c.note is None else f' -- {c.note}'
        row += f' /* {c.name}, {openings} opening{"" if openings == 1 else "s"}{note} */'
        rows.append(row)

    rows = '\n'.join(rows)

    openings = '\n'.join(
        f'  {ARRAY_MARKER}[{i}].edges[{w}] = {edge};'
        for i, c in enumerate(train.choppers)
        for w, edge in enumerate(c.edges) if isinstance(c.edges, tuple)
    )

    if train.export is None:
        handover = f'''
  /* nothing else reads the train, so give it back before leaving */
{_release(ARRAY_MARKER, tuple(i for i, c in enumerate(train.choppers) if isinstance(c.edges, tuple)))}'''
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
  chopper_parameters * {ARRAY_MARKER} = (chopper_parameters *) calloc(
    {count}, sizeof(chopper_parameters));
  if ({ARRAY_MARKER} == NULL) {{
    printf("{OUT_OF_MEMORY}\\n");
    exit(-1);
  }}
{rows}
  for (int {INDEX_MARKER} = 0; {INDEX_MARKER} < {count}; ++{INDEX_MARKER}) {{
    if ({ARRAY_MARKER}[{INDEX_MARKER}].edges == NULL) {{
      printf("{OUT_OF_MEMORY}\\n");
      exit(-1);
    }}
  }}
{openings}
  double chopcalc_latest = {source.latest_emission}; /* {source.latest_emission_note}, s */
  double chopcalc_min = {source.lambda_min}, chopcalc_max = {source.lambda_max};
  unsigned chopcalc_bands = chopper_wavelength_limits(
    &{source.lambda_min}, &{source.lambda_max},
    {count}, {ARRAY_MARKER},
    chopcalc_min, chopcalc_max, chopcalc_latest);
  if (chopcalc_bands == 0 || !({source.lambda_max} > {source.lambda_min})
      || {source.lambda_min} <= 0) {{
    /* chopper_wavelength_limits leaves its outputs alone when it finds nothing; putting
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


def _release(name: str, choppers: tuple[int, ...]) -> str:
    """Give back a train built by :func:`initialize_text`.

    Each row owns its slit edges, so those go first: freeing the row array alone loses
    every edge array with it. Emitted at the end of INITIALIZE when nothing else reads the
    train, and in FINALLY when something does -- the same lines, in one place or the other.

    Only the rows named in ``choppers`` are freed. A row whose edges are a DECLARE array
    -- what `NXDiskChopper` emits -- was never allocated, and handing that to ``free`` is
    undefined behaviour rather than a leak avoided.
    """
    lines = '\n'.join(
        f'    if ({name}[{i}].edges != NULL) free({name}[{i}].edges);' for i in choppers
    )
    return f'''{lines}
    free({name});'''


def finalize_text(export: Export) -> str:
    """Release a train INITIALIZE handed over."""
    return f'''
/* niess.chopcalc: release the published chopper train */
if ({export.choppers} != NULL) {{
{_release(export.choppers, export.values)}
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
