"""Chained positions are a convenience; absolute ones work just as well.

`at_relative` exists because BIFROST's geometry is specified as a chain of offsets --
each element so far past the one before it. When you instead know where things are,
from a survey or a CAD model, put those coordinates in the calibration directly.
"""
from pathlib import Path


def main(outdir: Path) -> None:
    from niess.components.chopper import disc_beam_offset
    from niess.instrument import Instrument, Mount
    from niess.mccode import to_mccode
    from niess.teaching import Primary, teaching_parameters

    # --8<-- [start:direct]
    from scipp import vector
    from scipp.spatial import rotations_from_rotvecs

    upright = rotations_from_rotvecs(vector([0, 0, 0.0], unit='deg'))

    # Positions as surveyed, in the instrument coordinate system -- no chaining
    calibration = teaching_parameters()
    for name, z in (('source', 0.0), ('chopper', 6.76), ('jaw', 7.26),
                    ('monitor', 7.46), ('sample_origin', 8.46)):
        calibration[name]['position'] = vector([0, 0, z], unit='m')
        calibration[name]['orientation'] = upright
    # A disc chopper's position is its spindle, not the point the beam crosses it. The
    # same function the chopper uses to find the beam from the spindle finds the spindle
    # from the beam, negated -- so the survey stays a survey and the geometry stays in
    # one place.
    chopper = calibration['chopper']
    calibration['chopper']['position'] -= disc_beam_offset(
        chopper['radius'], chopper['height'], beam_angle=chopper['beam_angle'])
    for name, z in (('unit_1', 1.5), ('unit_2', 3.51)):
        calibration['guides'][name]['position'] = vector([0, 0, z], unit='m')
        calibration['guides'][name]['orientation'] = upright

    surveyed = Instrument(name='teaching', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration(calibration)),
    ))
    instrument = to_mccode(surveyed)
    # --8<-- [end:direct]

    # ...and it is the same instrument the chained calibration produces
    def placements(params):
        built = to_mccode(Instrument(name='teaching', origin='sample_origin', parts=(
            Mount(name='primary', content=Primary.from_calibration(params)),)))
        return {c.name: tuple(float(str(x)) for x in c.at_relative[0])
                for c in built.components}

    chained, direct = placements(teaching_parameters()), placements(calibration)
    assert list(chained) == list(direct)
    # Chaining accumulates floating-point error the surveyed numbers do not have, so
    # compare the coordinates rather than their text
    worst = max(abs(a - b) for name in chained
                for a, b in zip(chained[name], direct[name]))
    assert worst < 1e-12, worst


if __name__ == '__main__':
    main(Path('.'))
