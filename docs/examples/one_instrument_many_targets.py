"""One instrument object, converted four ways.

Every target reads the same walk, so what each one produces comes from the tree rather
than from what an earlier target happened to emit.
"""
from pathlib import Path


def main(outdir: Path) -> None:
    # --8<-- [start:build]
    from niess.bifrost import Primary, Tank
    from niess.bifrost.parameters import primary_parameters, tank_parameters
    from niess.instrument import Instrument, Mount

    bifrost = Instrument(
        name='bifrost',
        origin='sample_origin',
        parts=(
            Mount(name='primary', content=Primary.from_calibration(primary_parameters())),
            # the tank is described in coordinates about the sample, so it hangs there
            Mount(name='tank', content=Tank.from_calibration(tank_parameters()),
                  relative_to='sample_origin'),
        ),
    )
    # --8<-- [end:build]

    # --8<-- [start:mccode]
    from niess.mccode import to_mccode

    instrument = to_mccode(bifrost)          # an mccode_antlr Instr
    # --8<-- [end:mccode]
    assert len(instrument.components) == 358

    # --8<-- [start:nexus]
    from niess.targets.nexus import BIFROST_REGISTRY, to_nexus_structure

    structure = to_nexus_structure(bifrost, registry=BIFROST_REGISTRY)
    # --8<-- [end:nexus]
    groups = [c for c in structure['children'][0]['children'][0]['children']
              if c.get('type') == 'group']
    assert len(groups) == 358

    # --8<-- [start:tof]
    from niess.tof import chopper_specs

    specs = chopper_specs(bifrost, origin=0.05)
    # --8<-- [end:tof]
    assert [s.name for s in specs] == [
        'pulse_shaping_chopper_1', 'pulse_shaping_chopper_2',
        'frame_overlap_chopper_1', 'frame_overlap_chopper_2',
        'bandwidth_chopper_1', 'bandwidth_chopper_2',
    ]

    # --8<-- [start:flow]
    graph = bifrost.to_graph()
    branches = list(graph.successors('tank/slits'))
    # --8<-- [end:flow]
    # ten paths leave the sample: nine channels and the elastic monitor
    assert len(branches) == 10

    # --8<-- [start:names]
    from niess.walk import visits

    where = {v.id: v for v in visits(bifrost)}
    analyzer = where['tank/channels[2]/pairs[0]/analyzer']
    # --8<-- [end:names]
    assert analyzer.emit_name('monochromator') == 'channel_3_1_monochromator'
    assert analyzer.frame == 'tank/channels[2]/pairs[0]/analyzer_point'


if __name__ == '__main__':
    main(Path('.'))
