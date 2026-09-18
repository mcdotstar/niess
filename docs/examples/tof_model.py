"""Set up a `tof` chopper-cascade model from an instrument niess emitted."""
from pathlib import Path


def main(outdir: Path) -> None:
    # --8<-- [start:build]
    from niess.instrument import Instrument, Mount
    from niess.teaching import Primary
    from niess.tof.tree import to_tof_model

    teaching = Instrument(name='teaching', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration()),
    ))

    setup = to_tof_model(teaching, neutrons=20_000)

    # In a notebook, displaying `setup` renders the table below. Everything it used came
    # from the instrument, so nothing has to be supplied -- but the knobs are listed so
    # you know which ones there are.
    print(setup)

    result = setup.model.run()
    # --8<-- [end:build]

    # every monitor, and the sample, records a time distribution
    assert setup.detectors == ('monitor', 'sample_origin')
    for name in setup.detectors:
        assert len(result.detectors[name].toa.data.flatten(to='e')) > 0

    # the chopper is where the beam path says it is, not where a straight line would
    assert abs(setup.choppers[0].distance - setup.source.distance.value - 6.76) < 1e-9

    # nothing needed supplying, and the report says so
    assert not any(use.overridden for use in setup.parameters)
    assert 'nothing has to be provided' in repr(setup)

    # --8<-- [start:override]
    faster = setup.with_values(chopperspeed=70.0)
    # --8<-- [end:override]
    assert faster.choppers[0].frequency == 70.0
    assert next(u for u in faster.parameters if u.name == 'chopperspeed').overridden

    (outdir / 'teaching_tof_setup.txt').write_text(repr(setup))


if __name__ == '__main__':
    main(Path('.'))
