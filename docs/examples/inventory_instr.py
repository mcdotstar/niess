"""Inventory an existing .instr file before translating it into a niess submodule."""
from pathlib import Path

INSTR = Path(__file__).parent / 'teaching_hand_written.instr'


def main(outdir: Path) -> None:
    # --8<-- [start:inventory]
    from niess.io.mccode import load_instr

    instrument = load_instr(INSTR)

    for instance in instrument.components:
        at, at_relative_to = instance.at_relative
        print(f'{instance.name:16s} {instance.type.name:20s} '
              f'AT {tuple(str(x) for x in at)} '
              f'RELATIVE {at_relative_to.name if at_relative_to else "ABSOLUTE"}')

    print('run-time parameters:', [p.name for p in instrument.parameters])
    # --8<-- [end:inventory]

    names = [c.name for c in instrument.components]
    assert names == ['source', 'unit_1', 'unit_2', 'chopper', 'jaw', 'monitor',
                     'sample_origin'], names
    assert sorted(p.name for p in instrument.parameters) == [
        'chopperdelay', 'chopperspeed', 'jaw_l', 'jaw_r',
    ]


if __name__ == '__main__':
    main(Path('.'))
