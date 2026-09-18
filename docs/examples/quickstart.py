"""The landing-page example: build BIFROST, convert it to NeXus Structure JSON.

Also the README's example, asserted here so the two cannot diverge.
"""
from pathlib import Path


def main(outdir: Path) -> None:
    # --8<-- [start:quickstart]
    from niess.bifrost import Primary, Tank
    from niess.bifrost.parameters import primary_parameters, tank_parameters
    from niess.instrument import Instrument, Mount
    from niess.nexus import to_nexus_structure
    from niess.nexus.bifrost import BIFROST_REGISTRY

    bifrost = Instrument(name='bifrost', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration(primary_parameters())),
        Mount(name='tank', content=Tank.from_calibration(tank_parameters()),
              relative_to='sample_origin'),
    ))

    structure = to_nexus_structure(bifrost, registry=BIFROST_REGISTRY)
    # --8<-- [end:quickstart]

    from niess.mccode import to_mccode
    assert len(to_mccode(bifrost).components) == 358
    instrument = structure['children'][0]['children'][0]
    assert len(instrument['children']) > 350


if __name__ == '__main__':
    main(Path('.'))
