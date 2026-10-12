"""Export BIFROST to STEP, with its detector tank turned, and find its parts by name."""
from pathlib import Path


def main(outdir: Path) -> None:
    # --8<-- [start:export]
    from niess.bifrost import bifrost
    from niess.brep import save_step

    save_step(bifrost.BIFROST, outdir / 'bifrost.step')
    # --8<-- [end:export]
    assert (outdir / 'bifrost.step').stat().st_size > 0

    # --8<-- [start:parameters]
    from niess.brep import to_assembly

    turned = to_assembly(bifrost.BIFROST,
                         parameters={'detector_tank_angle': 60, 'sample_rotation': 30})
    # --8<-- [end:parameters]

    # --8<-- [start:tree]
    def find(shape, label):
        if shape.label == label:
            return shape
        for child in shape.children:
            if (found := find(child, label)) is not None:
                return found

    print([part.label for part in turned.children])  # ['primary', 'sample', 'tank']
    analyzer = find(turned, 'channel_3_1_analyzer')
    print([blade.label for blade in analyzer.children])  # ['blade_0', 'blade_1', ...]
    # --8<-- [end:tree]
    assert [part.label for part in turned.children] == ['primary', 'sample', 'tank']
    assert len(analyzer.children) > 1

    # Turning the tank moves what it holds about the sample, and nothing else
    straight = to_assembly(bifrost.BIFROST)
    assert find(straight, 'moderator').center() == find(turned, 'moderator').center()
    before = find(straight, 'channel_3_1_analyzer').center()
    after = analyzer.center()
    assert abs(before.Y - after.Y) < 1e-9 and abs(before.X - after.X) > 0.1

    # --8<-- [start:refused]
    try:
        to_assembly(bifrost.BIFROST, parameters={'a4': 60})
    except ValueError as error:
        print(error)  # No frame turns by a4; the knobs are detector_tank_angle, sample_rotation
    # --8<-- [end:refused]
    else:
        raise AssertionError('a parameter no frame turns by was accepted')


if __name__ == '__main__':
    main(Path('.'))
