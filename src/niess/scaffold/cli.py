"""`niess-scaffold`: a `.instr` in, a niess submodule out."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog='niess-scaffold',
        description='Generate a first-draft niess submodule from a McStas .instr file.',
        epilog='The result is a starting point, not a finished model. Read the report.',
    )
    parser.add_argument('instr', type=Path, help='the .instr file to convert')
    parser.add_argument('-o', '--output', type=Path, default=Path('.'),
                        help='directory to write the module into (default: .)')
    parser.add_argument('--origin', default=None,
                        help='the component everything is measured against, usually the '
                             'sample position')
    parser.add_argument('--section', default='Primary',
                        help='name for the generated Section class (default: Primary)')
    parser.add_argument('--no-verify', action='store_true',
                        help='skip checking that the module places components where the '
                             '.instr does')
    parser.add_argument('--report-only', action='store_true',
                        help='print what would be converted, and write nothing')
    return parser


def main(argv: list[str] | None = None) -> int:
    from niess.io.mccode import load_instr
    from niess.mccode import to_mccode

    from .classify import convert, to_instrument
    from .emit import summary, write
    from .verify import compare

    arguments = build_parser().parse_args(argv)

    if not arguments.instr.is_file():
        print(f'niess-scaffold: {arguments.instr} is not a file', file=sys.stderr)
        return 2

    instr = load_instr(arguments.instr)
    conversion = convert(instr, origin=arguments.origin)

    print(summary(conversion))

    if not arguments.no_verify:
        comparison = compare(instr, to_mccode(to_instrument(conversion)))
        print()
        print(comparison.report())
        if not comparison.ok:
            print('\nniess-scaffold: the conversion does not place every component where '
                  f'{arguments.instr.name} does. Writing it anyway would produce a module '
                  'that describes a different instrument.', file=sys.stderr)
            return 1

    if arguments.report_only:
        return 0

    package = write(conversion, arguments.output, instr_path=arguments.instr,
                    section=arguments.section)
    print(f'\nwrote {package}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
