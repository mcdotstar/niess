"""Narrow a source's wavelength band to what its chopper train can pass."""
from pathlib import Path


def main(outdir: Path) -> None:
    # --8<-- [start:narrow]
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.chopcalc import narrow_source_wavelengths
    from niess.chopcalc import train_from_instrument
    from niess.instrument import Instrument, Mount
    from niess.mccode import to_mccode
    from niess.teaching import Primary

    teaching = Instrument(name='teaching', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration()),
    ))

    # The chopper train is read off the discs. Narrowing writes C into the instrument,
    # so it needs the assembler the McStas conversion built into -- it is a McStas-side
    # pass, and stays one.
    assembler = Assembler('teaching', flavor=Flavor.MCSTAS)
    to_mccode(teaching, assembler=assembler)
    train = narrow_source_wavelengths(
        assembler, train=train_from_instrument(teaching))

    print(f'narrowing {train.source.lambda_min}/{train.source.lambda_max} '
          f'of {train.source.name!r}')
    for chopper in train.choppers:
        openings = ', '.join(f'{low} to {high}' for low, high in chopper.windows)
        print(f'  {chopper.name:10s} {chopper.path:>8.8s} m from the source, '
              f'opening at {openings} deg')
    # --8<-- [end:narrow]

    # The band is computed at run time, so the row names parameters rather than numbers:
    # change --chopperdelay on the command line and the band recomputes.
    assert train.choppers[0].speed == 'chopperspeed'
    assert train.choppers[0].delay == 'chopperdelay'

    # The source says nothing about how long it emits for, so niess' own default of
    # three ESS pulses applies -- the same 0.008571 s that ESS_butterfly's own
    # tmax_multiplier=3 would have given, said in niess' terms rather than McStas'.
    assert train.source.latest_emission_note.startswith('default')

    text = str(assembler.instrument)
    # the library, and the guard that stops an older one being used silently
    assert '%include "chopper-lib"' in text
    assert 'CHOPPER_LIB_VERSION < 30000' in text
    # the narrowing writes through the source's own parameters
    assert '&source_lambda_min, &source_lambda_max' in text
    # and it is in the instrument's INITIALIZE, which runs before every component's
    assert 'multi_chopper_wavelength_limits' in text

    (outdir / 'teaching_narrowed.instr').write_text(text)


if __name__ == '__main__':
    main(Path('.'))
