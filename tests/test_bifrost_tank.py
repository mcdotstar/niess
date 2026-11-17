# SPDX-FileCopyrightText: 2025-present Gregory Tucker <gregory.tucker@ess.eu>
#
# SPDX-License-Identifier: MIT


def test_bifrost_tank_importable():
    from importlib.util import find_spec
    if not find_spec('niess'):
        raise RuntimeError('No niess available!')
    if not find_spec('niess.bifrost'):
        raise RuntimeError('No niess.bifrost available!')
    from niess.bifrost import Tank


def test_bifrost_tank_constructable():
    from niess.bifrost import Tank
    tank = Tank.from_calibration()
    assert len(tank.channels) == 9


def test_bifrost_tank_calibratable():
    from scipp import scalar, isclose
    from niess.bifrost import Tank
    from niess.bifrost.parameters import tank_parameters
    calibration = tank_parameters()
    tank = Tank.from_calibration(calibration)

    assert len(tank.channels) == 9

    vertical = 4.0, 3.674467758121384, 3.372105326299701, 3.1338895319560107, 2.9399369139099463
    horizontal = scalar(5.2, unit='deg')

    params = calibration['channels']
    for channel in tank.channels:
        assert len(channel.pairs) == 5
        for index, (analyzer, triplet) in enumerate((arm.analyzer, arm.detector) for arm in channel.pairs):
            assert analyzer.count == params['blade_count']['analyzer', index]
            hor_cov, ver_cov = analyzer.coverage(params['sample'], unit='deg')

            # The coverage should approximately match that specified in the calibration
            # For 2.7 meV, the vertical coverage is +/- 2 degrees (e.g., 4 degrees)
            # Higher final energies are smaller to have constant Q-perpendicular
            # coverage, with exact values following `vertical` above ... or calculated
            # from the ratio of kf values
            expected = scalar(vertical[index], unit='deg').to(unit=ver_cov.unit)
            assert ver_cov >= expected
            assert isclose(ver_cov, expected, atol=scalar(0.1, unit='deg'))
            # The analyzers have sufficient width to fully illuminate their detector
            # tubes, which means they are _wider_ than the detectors to account for
            # the finite crystal mosaic.
            mosaic = analyzer.central_blade.mosaic.to(unit='deg')
            # The detectors each cover (at least) 5.2 degrees horizontally for all energies
            # So the analyzer should be at least 5.2 + mosaic
            expected = mosaic + horizontal.to(unit=hor_cov.unit)
            assert hor_cov >= expected
            assert isclose(hor_cov, expected, atol=scalar(1.2, unit='deg'))

            # We can also extract the detector effective horizontal coverage
            # since we know the sample-to-analyzer and analyzer-to-detector distances:
            arm_hor, arm_ver = channel.pairs[index].coverage(params['sample'], unit='deg')
            # these should actually be identical
            assert isclose(arm_ver, ver_cov)
            # and the horizontal coverage is calculated from the tube length,
            # which should be much closer to the expected value of 5.2 degrees
            # but since the current parameters are the total length instead of the
            # _active_ length, this coverage is slightly too big
            assert isclose(arm_hor, horizontal, atol=scalar(0.6, unit='deg'))


def test_bifrost_tank_angles():
    """The main purpose of this test is to show how to get the (horizontal)
    scattering limit boundaries for a single setting of the tank position"""
    from scipp import vector, concat, scalar
    from niess.bifrost import Tank
    from niess.bifrost.parameters import tank_parameters
    params = tank_parameters()
    assert 'channels' in params
    assert 'elastic_monitor' in params

    tank = Tank.from_calibration(params)

    sample = vector(value=[0, 0, 0], unit='m')

    def a4_limits(ch):
        center = ch.sample_space_angle(sample).to(unit='deg')
        da4, _ = ch.coverage(sample, unit='deg')
        return center - da4/2, center + da4/2

    limits = [a4_limits(ch) for ch in tank.channels]

    flat = concat([x for l in limits for x in l], 'limits')
    # verify that the limits increase monotonically
    changes = flat[1:] - flat[:-1]
    assert all(c > scalar(0, unit='deg') for c in changes)


def test_bifrost_efu_parameters():
    from datetime import datetime
    from niess.bifrost import Tank
    from niess.bifrost.parameters import tank_parameters
    params = tank_parameters()
    tank = Tank.from_calibration(params)
    assert len(tank.channels) == 9
    after = datetime.now()
    efu_params = tank.efu_calibration()
    before = datetime.now()
    assert len(efu_params) == 1 and 'Calibration' in efu_params
    calibration = efu_params['Calibration']
    assert 'version' in calibration and calibration['version'] == 0
    assert 'instrument' in calibration and calibration['instrument'] == 'bifrost'
    assert 'date' in calibration
    date = datetime.fromisoformat(calibration['date'])
    assert after <= date <= before
    assert 'groups' in calibration and calibration['groups'] == 45
    assert 'groupsize' in calibration and calibration['groupsize'] == 3
    assert 'Parameters' in calibration
    params = calibration['Parameters']
    assert len(params) == 45
    for index, param in enumerate(params):
        assert 'groupindex' in param and param['groupindex'] == index
        assert 'intervals' in param and len(param['intervals']) == 3
        s = set()
        for interval in param['intervals']:
            assert len(interval) == 2
            assert all(0 <= x <= 1 for x in interval)
            s = s.union(interval)
        assert len(s) == 6
        assert 'polynomials' in param and len(param['polynomials']) == 3
        for polynomial in param['polynomials']:
            assert len(polynomial) == 4


def assembled_bifrost():
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.bifrost.parameters import primary_parameters, tank_parameters
    from niess.bifrost import Primary, Tank

    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    Primary.from_calibration(primary_parameters()).to_mccode(assembler)
    Tank.from_calibration(tank_parameters()).to_mccode(assembler, 'sample_origin')
    return assembler.instrument


def test_elastic_monitor_is_placed_and_rotated_in_the_tank_frame():
    """The elastic monitor turns with the tank.

    `sample` in Tank.to_mccode is the tank's rotating reference frame -- it shares
    the sample's origin but is not the sample. Positioning the monitor there while
    leaving its rotation to default (which Component.to_mccode makes ABSOLUTE) left
    the monitor's 59-degree orientation fixed in the lab while the tank turned
    around it.
    """
    monitor = next(c for c in assembled_bifrost().components if c.name == 'elastic_monitor')

    at_reference = monitor.at_relative[1]
    rotate_reference = monitor.rotate_relative[1]

    assert at_reference is not None
    assert rotate_reference is not None, 'rotation must not fall back to ABSOLUTE'
    assert at_reference.name == 'sample_origin'
    assert rotate_reference.name == 'sample_origin'


def test_bifrost_efu_groups_follow_the_efu():
    """Groups are numbered 15 * ring + 3 * arc + channel % 3, as the EFU numbers its readout."""
    from niess.bifrost import Tank
    from niess.bifrost.channel import efu_group
    from niess.bifrost.parameters import tank_parameters
    assert sorted(efu_group(c, a) for c in range(9) for a in range(5)) == list(range(45))
    assert [efu_group(c, 0) for c in range(9)] == [0, 1, 2, 15, 16, 17, 30, 31, 32]
    assert [efu_group(0, a) for a in range(5)] == [0, 3, 6, 9, 12]
    tank = Tank.from_calibration(tank_parameters())
    by_group = {p['groupindex']: p['intervals'] for p in tank.efu_calibration()['Calibration']['Parameters']}
    for c, channel in enumerate(tank.channels):
        for a, arm in enumerate(channel.pairs):
            assert by_group[efu_group(c, a)] == arm.efu_calibration().limits()
