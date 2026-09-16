"""Turn a McStas `.instr` into a first-draft niess submodule.

    niess-scaffold my_instrument.instr -o src/niess

One way, best-effort, and lossy by design. It reads an instrument, works out where every
component is, maps the ones it recognises onto niess classes, wraps the rest in `Opaque`,
and writes Python you then own and edit. It does not translate an instrument at run time:
the output is ordinary niess source, so there is still exactly one path into every target.

What it is for is the first hour of work, not the last. An instrumentalist with a working
`.instr` gets a module that already places everything correctly and already builds, plus a
list of what is still McStas-shaped. What it cannot do is decide what the instrument
*means* -- which components are one device, which numbers came off which drawing, what a
`TOF_monitor` actually is. That is the part worth a person's time, and the reason this
stops where it does.

    from niess.io.mccode import load_instr
    from niess.scaffold import convert, write

    conversion = convert(load_instr('my_instrument.instr'), origin='sample')
    print(summary(conversion))
    write(conversion, 'src/niess', instr_path='my_instrument.instr')
"""
from .classify import Conversion, Mapped, convert, to_instrument
from .emit import summary, write
from .fold import declared_variables, folder, symbol_table
from .place import Placement, placements
from .recipes import RECIPES
from .verify import Comparison, check_against_mccode, compare

__all__ = [
    'Comparison',
    'Conversion',
    'Mapped',
    'Placement',
    'RECIPES',
    'check_against_mccode',
    'compare',
    'convert',
    'declared_variables',
    'folder',
    'placements',
    'summary',
    'symbol_table',
    'to_instrument',
    'write',
]
