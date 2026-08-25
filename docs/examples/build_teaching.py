"""Assemble the teaching instrument into a McStas instrument.

Run directly (``python docs/examples/build_teaching.py``) or via the test suite.
"""
from pathlib import Path


def main(outdir: Path) -> None:
    # --8<-- [start:assemble]
    from niess.instrument import Instrument, Mount
    from niess.mccode import to_mccode
    from niess.teaching import Primary

    teaching = Instrument(name='teaching', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration()),
    ))
    instrument = to_mccode(teaching)
    # --8<-- [end:assemble]

    # The calibration produced these McStas components, in beam order
    emitted = [(c.name, c.type.name) for c in instrument.components]
    assert emitted == [
        ('source', 'ESS_butterfly'),
        ('unit_1', 'Guide_gravity'),
        ('unit_2', 'Guide_gravity'),
        ('chopper', 'DiskChopper'),
        ('jaw', 'Slit'),
        ('monitor', 'Frame_monitor'),
        ('sample_origin', 'Arm'),
    ], emitted

    # ...and these run-time knobs, which nothing had to declare by hand: the jaw and
    # the chopper generate their own, and the source wavelengths were given as
    # instrument-parameter specifications in the calibration.
    assert sorted(p.name for p in instrument.parameters) == [
        'chopperdelay', 'chopperspeed', 'jaw_l', 'jaw_r',
        'source_lambda_max', 'source_lambda_min',
    ]

    # The guide section became its own included instrument
    assert [i.name for i in instrument.included] == ['teaching_guides']

    (outdir / 'teaching.instr').write_text(str(instrument))


if __name__ == '__main__':
    main(Path('.'))
