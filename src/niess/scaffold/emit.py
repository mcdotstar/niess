"""Write a `Conversion` out as a niess submodule.

The shape is `src/niess/teaching/`, which is the shipped worked example and what
"Build a new instrument submodule" documents: a `parameters.py` of nested calibration
dictionaries, a `primary.py` declaring the structure as typed fields in beam order, and an
`instrument.py` assembling the two. A generated module is meant to be read, edited and
committed by whoever asked for it, so it is written the way a person would write it rather
than as data for a machine to reload.

Two choices worth knowing about.

**Placements are chained, not absolute.** Each component is placed with `at_relative`
against the one the `.instr` measured it from, so the chain that made the original
maintainable is still there and moving something upstream still moves everything after it.
Absolute numbers would be correct and dead.

**Folded parameters come back as named constants.** The geometry is resolved with each
instrument parameter at its default -- a niess calibration is numbers -- but emitting the
bare number throws away what the author meant. `AT (0, 0, GUI_start)` becomes
``GUI_start * z`` against a module constant, so the relationships survive as Python even
though they are no longer run-time. Which parameters this happened to is reported, because
it is the one genuinely lossy step in the conversion.
"""
from __future__ import annotations

import ast
import keyword
from pathlib import Path
from typing import Any

from scipp import DType, Variable

HEADER = '''"""{title}

Generated from {source} by `niess.scaffold`. **Not a finished niess model.**

{summary}

What to do with it, roughly in order:

* Replace `Opaque` components with real niess classes, most frequent first. Each one you
  replace is a component that NeXus and CAD can then say something about; an `Opaque`
  emits McStas and nothing else.
* Group the flat `{section}` into nested `Section`s that mean something -- a guide bank,
  a chopper cascade. Field order is beam order and must stay that way.
* Re-express the numbers in the units they were measured in. Everything here is metres
  and degrees because that is all a `.instr` carries; a calibration is easier to check
  against a drawing when it reads `1500 * mm`.
* Decide which frozen constants should be run-time parameters again, and which are
  properly fixed geometry.

The `.instr` this came from is kept beside this module, and `test_placement.py` checks
that every component still lands where that file puts it. Keep both.
"""
'''


def _identifier(name: str, taken: set[str]) -> str:
    """A McStas instance name as a Python field name."""
    candidate = name if name.isidentifier() else ''.join(
        character if character.isalnum() or character == '_' else '_' for character in name
    )
    if not candidate or candidate[0].isdigit():
        candidate = f'c_{candidate}'
    if keyword.iskeyword(candidate) or candidate.startswith('_'):
        candidate = f'{candidate}_'
    while candidate in taken:
        candidate = f'{candidate}_'
    taken.add(candidate)
    return candidate


def _number(value: float) -> str:
    """A float as the shortest Python literal that round-trips to it."""
    return repr(float(value))


def _variable(value: Variable) -> str:
    """A scipp `Variable` as the call that rebuilds it."""
    unit = '' if value.unit is None else str(value.unit)
    if value.dtype == DType.vector3:
        values = ', '.join(_number(v) for v in value.value)
        return f"vector([{values}], unit='{unit}')"
    if value.dtype == DType.rotation3:
        # written as the McCode angles that produced it, which is what a reader can check
        # against the `.instr`; the quaternion itself says nothing.
        from ..spatial import mccode_ordered_angles
        angles = ', '.join(_number(a) for a in mccode_ordered_angles(value))
        return f'mccode_quaternion({angles})'
    if value.dims:
        values = ', '.join(_number(v) for v in value.values)
        dims = ', '.join(repr(d) for d in value.dims)
        return f"array(values=[{values}], dims=[{dims}], unit='{unit}')"
    return f"scalar({_number(value.value)}, unit='{unit}')"


def _literal(value: Any, indent: int = 0) -> str:
    pad = ' ' * indent
    if isinstance(value, Variable):
        return _variable(value)
    if value is None or isinstance(value, bool):
        return repr(value)
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, dict):
        if not value:
            return '{}'
        inner = ',\n'.join(f'{pad}    {key!r}: {_literal(item, indent + 4)}'
                           for key, item in value.items())
        return '{\n' + inner + f',\n{pad}}}'
    if isinstance(value, (list, tuple)):
        inner = ', '.join(_literal(item, indent) for item in value)
        return f'[{inner}]'
    return repr(value)


def _axis_source(expression, number, constants: set[str]) -> str:
    """One `AT`/`ROTATED` component, written symbolically where that is safe.

    "Safe" means every name the expression uses is one of the constants this module
    defines. Checked by parsing what `Expr.to_python` produced and reading the names back
    out of it, which also rules out anything needing an import -- a `sqrt` appears as a
    name that is not a constant, so the expression falls back to its number rather than
    generating a module that will not run.
    """
    if expression is None or getattr(expression, 'is_constant', True):
        return _number(number)
    try:
        source = expression.to_python()
        names = {node.id for node in ast.walk(ast.parse(source, mode='eval'))
                 if isinstance(node, ast.Name)}
    except Exception:
        return _number(number)
    if names and names <= constants:
        return source
    return _number(number)


def _local_vector(placement, constants: set[str]) -> str:
    parts = [_axis_source(source, number, constants)
             for source, number in zip(placement.local_position_source,
                                       placement.local_position.value)]
    return f"vector([{', '.join(parts)}], unit='m')"


def _local_angles(placement, constants: set[str]) -> str:
    parts = [_axis_source(source, number, constants)
             for source, number in zip(placement.local_angles_source,
                                       placement.local_angles)]
    return f"mccode_quaternion({', '.join(parts)})"


def parameters_module(conversion, fields: dict[str, str]) -> str:
    """`parameters.py`: every number the instrument needs, chained as the original was."""
    constants = set(conversion.frozen)
    lines = [
        '"""Calibration for {name}, as read from {source}.'.format(
            name=conversion.name, source=conversion.source),
        '',
        'Positions are *chained*: each component is placed relative to the one the',
        'original `.instr` measured it from, so changing something upstream still moves',
        'everything downstream, and no number is written twice.',
        '',
        'Everything is in metres and degrees, which is all a `.instr` carries. Numbers',
        'read off a drawing are easier to check in the units of the drawing -- see the',
        '"Translate a McStas .instr" guide.',
        '"""',
        'from scipp import array, scalar, vector',
        '',
        'from niess.spatial import at_relative, mccode_quaternion',
        '',
    ]

    if conversion.frozen:
        lines += [
            '',
            '# Instrument parameters of the original that drove the geometry. The',
            '# placements below were resolved with these values, so they are constants',
            '# here rather than run-time knobs -- the one genuinely lossy step in the',
            '# conversion. Promote any of them back to an instrument parameter if the',
            '# geometry really should follow it.',
        ]
        for name in sorted(conversion.frozen):
            lines.append(f'{name} = {_number(conversion.frozen[name])}')
        lines.append('')

    lines += [
        '', f'def {conversion.name}_parameters():',
        '    """Every number, in beam order."""',
        '    # `at` is where the original `.instr` put each component, and the chain',
        '    # is built from it. That matters wherever a niess class measures from a',
        '    # different point than the McStas component it emits -- a disc chopper',
        '    # is placed by its spindle while the `.instr` places the beam crossing',
        '    # -- because everything downstream still hangs off the *crossing*.',
        '    # Chaining off the niess position instead would carry that offset into',
        '    # every later component, which is the error the "Translate a McStas',
        '    # .instr" guide warns about.',
        '    at, orientation = {}, {}',
        '']

    for mapped in conversion.components:
        placement = mapped.placement
        reference = placement.at_reference
        rotation_reference = placement.rotate_reference
        lines.append(f'    # {mapped.name} = {mapped.mccode_type}'
                     f' -> {mapped.niess_class.__name__}')

        turn = _local_angles(placement, constants)
        if rotation_reference is None:
            lines.append(f"    orientation[{mapped.name!r}] = {turn}")
        else:
            lines.append(f"    orientation[{mapped.name!r}] = "
                         f"orientation[{rotation_reference!r}] * {turn}")

        local = _local_vector(placement, constants)
        if reference is None:
            placed = local
        else:
            placed = (f"at_relative(at[{reference!r}], "
                      f"orientation[{reference!r}], {local})")
        lines.append(f"    at[{mapped.name!r}] = {placed}")
        lines.append('')

    lines.append('    return {')
    for mapped in conversion.components:
        field = fields[mapped.name]
        lines.append(f'        {field!r}: {{')
        lines.append(f'            {"name"!r}: {mapped.name!r},')
        if mapped.position_offset is None:
            lines.append(f"            'position': at[{mapped.name!r}],")
        else:
            lines.append(
                f"            # a {mapped.niess_class.__name__} is placed by its own"
                " reference point, not by"
            )
            lines.append(
                "            # the beam crossing the `.instr` gave; this is the vector"
                " between them."
            )
            lines.append(f"            'position': at[{mapped.name!r}] + "
                         f"{_variable(mapped.position_offset)},")
        lines.append(f"            'orientation': orientation[{mapped.name!r}],")
        for key, value in mapped.calibration.items():
            lines.append(f'            {key!r}: {_literal(value, 12)},')
        lines.append('        },')
    lines.append('    }')
    lines.append('')
    return '\n'.join(lines)


def structure_module(conversion, fields: dict[str, str], section: str) -> str:
    """`primary.py`: the structure, as typed fields in beam order."""
    used = sorted({mapped.niess_class.__name__ for mapped in conversion.components}
                  | {'Section'})
    lines = [
        f'"""The structure of {conversion.name}.',
        '',
        'A `Section` is a declaration, not code: an ordered list of typed fields naming',
        'the components in beam order. `Section.from_calibration` constructs them',
        '**positionally**, so this declaration order *is* the beam order and it must',
        f'match the keys built by `{conversion.name}_parameters`.',
        '',
        'This is one flat section because a converter cannot tell which components',
        'belong together -- that is a judgement about the instrument. Grouping runs of',
        'them into nested `Section`s is the next thing worth doing; each nested one',
        'becomes a `%include` in the emitted McStas.',
        '"""',
        f'from niess.components import {", ".join(used)}',
        'from niess.utilities import calibration',
        '',
        '',
        f'class {section}(Section):',
        f'    """Every component of {conversion.name}, in beam order."""',
    ]
    for mapped in conversion.components:
        comment = (f'  # {mapped.mccode_type}'
                   if mapped.is_opaque else '')
        lines.append(f'    {fields[mapped.name]}: {mapped.niess_class.__name__}{comment}')
    lines += [
        '',
        '    # Emit into the caller\'s assembler rather than nesting the whole instrument',
        '    # inside itself. Underscored fields are Section extras rather than',
        '    # components, so they are invisible to parts()/types()/items().',
        '    _flat: bool = True',
        '',
        '    @classmethod',
        '    @calibration',
        '    def from_calibration(cls, parameters: dict):',
        '        """Build from a calibration dictionary, defaulting to the shipped one."""',
        f'        from .parameters import {conversion.name}_parameters',
        '        if len(parameters) == 0:',
        f'            parameters = {conversion.name}_parameters()',
        '        return super().from_calibration(parameters)',
        '',
    ]
    return '\n'.join(lines)


def instrument_module(conversion, section: str) -> str:
    """`instrument.py`: the whole thing, as one `Instrument`."""
    lines = [
        f'"""{conversion.name} as a single `Instrument`.',
        '',
        'This is the object every niess target takes: `niess.mccode.to_mccode`,',
        '`niess.nexus.to_nexus_structure`, and the rest.',
        '"""',
        'from mccode_antlr.common import InstrumentParameter',
        '',
        'from niess.instrument import Instrument, Mount',
        '',
        f'from .{"structure"} import {section}',
        '',
        '',
        'def instrument():',
        f'    """Build {conversion.name} from its shipped calibration."""',
        '    return Instrument(',
        f'        name={conversion.name!r},',
        f'        origin={conversion.origin!r},',
        '        parts=(',
        f'            Mount(name={section.lower()!r}, content={section}.from_calibration()),',
        '        ),',
    ]
    if conversion.parameters:
        lines.append('        parameters=(')
        for parameter in conversion.parameters:
            lines.append(f'            InstrumentParameter.parse({str(parameter)!r}),')
        lines.append('        ),')
    lines += [
        '    )',
        '',
        '',
        f'{conversion.name.upper().replace("-", "_")} = instrument()',
        '',
    ]
    return '\n'.join(lines)


def summary(conversion) -> str:
    """The report, as prose. Also what `niess-scaffold` prints."""
    from collections import Counter

    total = len(conversion.components)
    modelled = len(conversion.modelled)
    lines = [f'{modelled} of {total} components were mapped onto niess classes; '
             f'{total - modelled} became `Opaque`.']

    if conversion.modelled:
        counted = Counter(m.niess_class.__name__ for m in conversion.modelled)
        lines += ['', 'Modelled:']
        lines += [f'  {count:4d}  {name}' for name, count in counted.most_common()]

    if conversion.opaque:
        counted = Counter(m.mccode_type for m in conversion.opaque)
        lines += ['', 'Still `Opaque`, most frequent first -- this is the to-do list:']
        lines += [f'  {count:4d}  {name}' for name, count in counted.most_common()]

    if conversion.subsumed:
        lines += ['', 'Instrument parameters now declared by the component that owns them,',
                  'rather than carried forward (same name, same default):']
        lines += [f'  {name} -> {owner}' for name, owner in sorted(conversion.subsumed.items())]

    if conversion.frozen:
        lines += ['', 'Instrument parameters that drove geometry and are now constants.',
                  'The geometry no longer follows them:']
        lines += [f'  {name} = {value:g}' for name, value in sorted(conversion.frozen.items())]

    if conversion.parameters:
        lines += ['', 'Run-time parameters carried forward:',
                  '  ' + ', '.join(p.name for p in conversion.parameters)]

    return '\n'.join(lines)


def init_module(conversion, section: str) -> str:
    title = f'{conversion.name}, converted from McStas.'
    return HEADER.format(
        title=title,
        source=conversion.source,
        summary=summary(conversion),
        section=section,
    ) + '\n'.join([
        f'from .instrument import instrument, {conversion.name.upper().replace("-", "_")}',
        f'from .parameters import {conversion.name}_parameters',
        f'from .structure import {section}',
        '',
        '__all__ = [',
        f'    {conversion.name.upper().replace("-", "_")!r},',
        f'    {section!r},',
        "    'instrument',",
        f'    {conversion.name + "_parameters"!r},',
        ']',
        '',
    ])


def test_module(conversion, instr_name: str) -> str:
    """A test that the generated module still places everything where the `.instr` does."""
    return '\n'.join([
        f'"""Does this module still describe the instrument it was converted from?',
        '',
        'Not a text diff -- the generated McStas will never match the original, and',
        'should not: different ordering, added metadata, a chopper that may come apart',
        'into one component per opening. What must match is where the components *are*.',
        '',
        'Keep this test. It is the only thing that will report a later edit moving a',
        'component by a millimetre.',
        '"""',
        'from pathlib import Path',
        '',
        'from niess.io.mccode import load_instr',
        'from niess.mccode import to_mccode',
        'from niess.scaffold.verify import compare',
        '',
        f'from . import instrument',
        '',
        f'INSTR = Path(__file__).parent / {instr_name!r}',
        '',
        '',
        'def test_every_component_is_where_the_instr_puts_it():',
        '    original = load_instr(INSTR)',
        '    converted = to_mccode(instrument())',
        '    comparison = compare(original, converted)',
        '    assert comparison.ok, comparison.report()',
        '',
    ])


def write(conversion, outdir: Path, instr_path: Path | None = None,
          section: str = 'Primary') -> Path:
    """Write the module, and return the directory it was written to."""
    from shutil import copyfile

    package = Path(outdir) / conversion.name
    package.mkdir(parents=True, exist_ok=True)

    taken: set[str] = set()
    fields = {mapped.name: _identifier(mapped.name, taken)
              for mapped in conversion.components}

    (package / 'parameters.py').write_text(parameters_module(conversion, fields))
    (package / 'structure.py').write_text(structure_module(conversion, fields, section))
    (package / 'instrument.py').write_text(instrument_module(conversion, section))
    (package / '__init__.py').write_text(init_module(conversion, section))

    if instr_path is not None and Path(instr_path).is_file():
        instr_name = Path(instr_path).name
        copyfile(instr_path, package / instr_name)
        (package / 'test_placement.py').write_text(test_module(conversion, instr_name))

    return package
