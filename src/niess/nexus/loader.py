"""Read an instrument from a file.

niess translates niess instruments; this is not a translation front-end. It exists so a
`.instr` can be *read* -- to inspect its placements, or to check a niess submodule against
the hand-written file it replaces (see ``docs/examples/verify_translation.py``). Converting
an instrument niess did not build is deliberately not supported.
"""
from __future__ import annotations

from pathlib import Path


def load_instr(filepath: str | Path):
    """Load an ``Instr`` from a McCode ``.instr`` file or a serialized instrument."""
    filepath = Path(filepath)
    if not filepath.is_file():
        raise ValueError(f'{filepath} does not exist or is not a file')

    suffix = filepath.suffix.lower()
    if suffix == '.instr':
        from mccode_antlr.loader import load_mcstas_instr
        return load_mcstas_instr(filepath)
    if suffix == '.json':
        from mccode_antlr.io.json import load_json
        return load_json(filepath)
    if suffix in ('.msgpack', '.mpk'):
        from mccode_antlr.io.msgpack import load_msgpack
        return load_msgpack(filepath)

    raise ValueError(f'Cannot load an instrument from {filepath.suffix} files')
