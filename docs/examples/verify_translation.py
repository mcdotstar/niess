"""Prove a translation: compare absolute placements, not text.

A niess submodule will never emit byte-identical McStas to the file it replaces --
different names, different ordering, extra metadata. What must match is where the
components actually are.
"""
from pathlib import Path

INSTR = Path(__file__).parent / 'teaching_hand_written.instr'


def main(outdir: Path) -> None:
    # --8<-- [start:verify]
    from niess.instrument import Instrument, Mount
    from niess.io.mccode import load_instr
    from niess.mccode import to_mccode
    from niess.teaching import Primary

    # the hand-written file, read as it is -- there is no tree for it yet
    original = load_instr(INSTR)

    # and the submodule that is meant to replace it
    translated = to_mccode(Instrument(
        name='teaching', origin='sample_origin',
        parts=(Mount(name='primary', content=Primary.from_calibration()),)))

    # resolve_orientations() gives each component's absolute placement
    before = original.resolve_orientations()
    after = translated.resolve_orientations()

    for name in (c.name for c in original.components):
        assert name in after, f'{name} missing from the translation'
        assert before[name].position() == after[name].position(), name
    # --8<-- [end:verify]

    assert len(before) == len(after) == 7


if __name__ == '__main__':
    main(Path('.'))
