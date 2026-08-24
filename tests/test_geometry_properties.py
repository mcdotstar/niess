"""The geometry properties are what the emitted instrument is actually built from.

The composites used to work these numbers out inside ``to_mccode``, so only the McStas
conversion could see them. Moving them onto the objects is only safe if they still agree
with what gets emitted -- and staying in agreement is the point, since the walk rewrite
will have the McStas translator read them off the object rather than recompute them.

So these compare the property against the emitted component, rather than against a
number written down here: a hard-coded expectation would go stale with the calibration
and prove nothing about the emission.
"""
import pytest

from niess.dispatch import expr_float


@pytest.fixture(scope='module')
def tank():
    from niess.bifrost import Tank
    from niess.bifrost.parameters import tank_parameters
    return Tank.from_calibration(tank_parameters())


@pytest.fixture(scope='module')
def emitted(tank):
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters

    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    Primary.from_calibration(primary_parameters()).to_mccode(assembler)
    tank.to_mccode(assembler, 'sample_origin')
    return {c.name: c for c in assembler.instrument.components}


def at_vector(instance):
    return [expr_float(v) for v in instance.at_relative[0]]


def rotate_angles(instance):
    return [expr_float(v) for v in instance.rotate_relative[0]]


def test_channel_cassette_angle_is_the_emitted_rotation(tank, emitted):
    for index, channel in enumerate(tank.channels):
        instance = emitted[f'channel_{index + 1}_arm']
        assert rotate_angles(instance) == pytest.approx([0, channel.cassette_angle.value, 0])


def test_arm_sample_analyzer_distance_is_the_emitted_placement(tank, emitted):
    for channel_index, channel in enumerate(tank.channels):
        for arm_index, arm in enumerate(channel.pairs):
            name = f'channel_{channel_index + 1}_{arm_index + 1}_analyzer_point'
            assert at_vector(emitted[name]) == pytest.approx(
                [0, 0, arm.sample_analyzer_distance.value]
            ), name


def test_arm_theta_is_the_emitted_detector_angle(tank, emitted):
    for channel_index, channel in enumerate(tank.channels):
        for arm_index, arm in enumerate(channel.pairs):
            name = f'channel_{channel_index + 1}_{arm_index + 1}_detector_angle'
            assert rotate_angles(emitted[name]) == pytest.approx(
                [0, arm.analyzer_theta.value, 0]
            ), name


def test_arm_analyzer_detector_distance_is_the_emitted_placement(tank, emitted):
    for channel_index, channel in enumerate(tank.channels):
        for arm_index, arm in enumerate(channel.pairs):
            name = f'channel_{channel_index + 1}_{arm_index + 1}_triplet'
            assert at_vector(emitted[name]) == pytest.approx(
                [0, 0, arm.analyzer_detector_distance.value]
            ), name


def test_arm_scattering_angle_is_twice_theta(tank):
    arm = tank.channels[0].pairs[0]
    assert arm.analyzer_theta.value == pytest.approx(arm.scattering_angle.value / 2)


def test_slit_width_stays_inside_the_channel_spacing(tank):
    """Adjacent slits must not overlap, or a neutron is tagged with two channels."""
    assert tank.slit_width < tank.channel_spacing


def test_slit_width_clears_the_analyzer(tank):
    """...and must not clip the analyzer it is there to tag neutrons into."""
    from scipp import vector
    origin = vector([0, 0, 0], unit='m')
    widest = max(channel.pairs[0].analyzer.coverage(origin, unit='radian')[0].value
                 for channel in tank.channels)
    assert tank.slit_width > widest


def test_no_two_slits_overlap(tank):
    """Every slit, the elastic monitor's included, keeps clear of its neighbours."""
    angles = sorted(tank.slit_angles)
    for lower, upper in zip(angles, angles[1:]):
        assert upper - lower >= tank.slit_width


def test_channel_spacing_takes_the_smallest_gap(tank, monkeypatch):
    """A calibration may supply its own angles, and they need not be evenly spaced."""
    from niess.bifrost.tank import Tank
    monkeypatch.setattr(Tank, 'channel_angles',
                        property(lambda self: [0.0, 0.5, 0.7, 1.4]))
    assert tank.channel_spacing == pytest.approx(0.2)
    assert tank.slit_width < 0.2


def test_channel_spacing_refuses_a_single_channel(tank, monkeypatch):
    """Rather than inventing a width the layout does not imply."""
    from niess.bifrost.tank import Tank
    monkeypatch.setattr(Tank, 'channel_angles', property(lambda self: [0.0]))
    with pytest.raises(ValueError, match='fewer than two channels'):
        _ = tank.channel_spacing


def test_tank_slit_geometry_is_what_the_radial_slits_are_built_from(tank, emitted):
    slits = emitted['slits']
    assert expr_float(slits.get_parameter('slit_width').value) == pytest.approx(
        tank.slit_width
    )
    assert expr_float(slits.get_parameter('number').value) == len(tank.slit_angles)


def test_tank_slit_angles_are_the_declared_array(tank):
    """The angles reach McStas as a DECLARE'd C array, not as a component parameter."""
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler

    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    assembler.component('sample_origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    tank.to_mccode(assembler, 'sample_origin')

    declared = [block.source for block in assembler.instrument.declare
                if 'slits_positions' in block.source]
    assert len(declared) == 1, 'expected exactly one slits_positions array'
    values = [float(v) for v in
              declared[0].split('{')[1].split('}')[0].split(',')]
    assert values == pytest.approx(tank.slit_angles)


def test_tank_slit_angles_end_with_the_elastic_monitor(tank):
    """The monitor's slit is added last, which is what its emitted WHEN relies on."""
    assert tank.slit_angles[:-1] == tank.channel_angles
    assert tank.slit_angles[-1] == tank.monitor_angle
    assert len(tank.slit_angles) == len(tank.channels) + 1


def test_disc_chopper_opening_turns_match_the_slits():
    """The disc's timing geometry, without any of the McStas delay machinery."""
    from scipp import array, scalar, vector
    from scipp.spatial import rotations_from_rotvecs
    from niess.components import DiscChopper

    disc = DiscChopper.from_calibration({
        'name': 'pack',
        'position': vector([0, 0, 5.0], unit='m'),
        'orientation': rotations_from_rotvecs(vector([0, 0, 0.0], unit='deg')),
        'radius': scalar(0.35, unit='m'),
        'height': scalar(0.06, unit='m'),
        'frequency': scalar(14.0, unit='Hz'),
        'top_dead_center': scalar(15.0, unit='deg'),
        'beam_position': scalar(90.0, unit='deg'),
        'windows': array(values=[10.0, 30.0, 100.0, 140.0, 350.0, 370.0],
                         dims=['edges'], unit='deg'),
    })

    turns = disc.opening_turns()
    assert len(turns) == len(disc.slits()) == 3
    assert all(0 <= turn < 360 for turn in turns)
    # the beam sits 90 degrees from the mark, and the openings are centred on 20, 120
    # and 360 -- so each turn is (90 - centre) wrapped into one revolution
    assert turns == pytest.approx([70.0, 330.0, 90.0])
