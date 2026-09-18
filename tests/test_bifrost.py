# SPDX-FileCopyrightText: 2025-present Gregory Tucker <gregory.tucker@ess.eu>
#
# SPDX-License-Identifier: MIT
from operator import getitem


def test_bifrost_whole():
    from niess.bifrost.parameters import primary_parameters, tank_parameters
    from niess.bifrost import Tank, Primary

    primary = Primary.from_calibration(primary_parameters())
    tank = Tank.from_calibration(tank_parameters())


def test_bifrost_mccode(tmp_path):
    from niess.bifrost.parameters import primary_parameters, tank_parameters
    from niess.bifrost import Tank, Primary
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler

    bifrost = Assembler('bifrost', flavor=Flavor.MCSTAS)

    primary = Primary.from_calibration(primary_parameters())
    primary.to_mccode(bifrost)

    # TODO insert pre- and post-sample things here
    #      e.g., the split_at location at the end of the guide
    #      any filters, e.g., a hits-the-sample MCPL filter, or a Be-transmission filter
    #      the radial collimator between sample and tank, etc.
    bifrost.component('sample', 'Arm', at=([0,0,0], 'sample_origin'))

    tank = Tank.from_calibration(tank_parameters())
    with bifrost.included('bifrost_tank') as tank_assembler:
        tank.to_mccode(tank_assembler, 'sample_origin', flat=False)

    # Extraction writes the whole %include tree out as files; do it somewhere
    # disposable. It used to land in the working directory, leaving a bifrost_extract/
    # of 58 .instr files in the source tree every time the suite ran.
    from mccode_antlr.io import extract
    extract.extract_to_directory(bifrost.instrument, tmp_path / 'bifrost_extract')
    assert (tmp_path / 'bifrost_extract').is_dir()

    # The Instr-JSON comparison that used to live here is gone with
    # tests/bifrost_assembler.json. It was commented out because a raw mccode-antlr
    # serialisation is not stable across upstream releases -- the file had gone stale by
    # a release, still carrying pulse_shaping_chopper_1phase after 0.6.0 renamed it to
    # delay. tests/test_baseline.py freezes what niess actually decides instead.
