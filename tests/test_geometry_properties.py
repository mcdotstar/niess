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


def wedge_angle(wedge):
    """Where a wedge points, in radians about the vertical axis.

    Read back off the orientation rather than taken from a stored number, so it is the
    angle the emission will actually use.
    """
    from scipp import vector, atan2
    at = wedge.orientation * vector([0, 0, 1.])
    return atan2(y=at.fields.x, x=at.fields.z).to(unit='radian').value


def wedge_width(wedge):
    """The angular width of a wedge, in radians."""
    return wedge.angle_width.to(unit='radian').value


def test_a_wedge_points_at_the_channel_it_tags(tank):
    """The wedge and its cassette have to agree, or the tag names the wrong channel.

    Both turn about the vertical, which is y here. A wedge built about z instead
    lands at the same angle in the wrong plane, and the only one that survives it is
    the middle wedge -- whose rotation is the identity either way.
    """
    for index, (wedge, channel) in enumerate(zip(tank.filters, tank.channels)):
        assert wedge_angle(wedge) == pytest.approx(
            channel.cassette_angle.to(unit='radian').value, abs=1e-9
        ), f'wedge_{index}'


def test_wedge_width_stays_inside_the_channel_spacing(tank):
    """Adjacent wedges must not overlap, or a neutron is tagged with two channels.

    The wedges do the tagging that the radial slits used to: a neutron scatters in at
    most one of them, and its EXTEND is what writes `secondary_cassette`. Overlapping
    wedges would let the first one reached claim a neutron aimed at its neighbour.
    """
    for index, wedge in enumerate(tank.filters):
        assert wedge_width(wedge) < tank.channel_spacing, f'wedge_{index}'


def test_wedge_width_clears_the_analyzer(tank):
    """...and must not clip the analyzer it is there to tag neutrons into."""
    from scipp import vector
    origin = vector([0, 0, 0], unit='m')
    widest = max(channel.pairs[0].analyzer.coverage(origin, unit='radian')[0].value
                 for channel in tank.channels)
    for index, wedge in enumerate(tank.filters):
        assert wedge_width(wedge) > widest, f'wedge_{index}'


def test_no_two_wedges_overlap(tank):
    """Each keeps clear of its neighbours, so no neutron is inside two at once."""
    angles = sorted(wedge_angle(w) for w in tank.filters)
    widest = max(wedge_width(w) for w in tank.filters)
    for lower, upper in zip(angles, angles[1:]):
        assert upper - lower >= widest


def test_channel_spacing_takes_the_smallest_gap(tank, monkeypatch):
    """A calibration may supply its own angles, and they need not be evenly spaced."""
    from niess.bifrost.tank import Tank
    monkeypatch.setattr(Tank, 'channel_angles',
                        property(lambda self: [0.0, 0.5, 0.7, 1.4]))
    assert tank.channel_spacing == pytest.approx(0.2)


def test_channel_spacing_refuses_a_single_channel(tank, monkeypatch):
    """Rather than inventing a width the layout does not imply."""
    from niess.bifrost.tank import Tank
    monkeypatch.setattr(Tank, 'channel_angles', property(lambda self: [0.0]))
    with pytest.raises(ValueError, match='fewer than two channels'):
        _ = tank.channel_spacing


def test_wedge_geometry_is_what_the_emitted_filter_is_built_from(tank, emitted):
    """Each wedge object, against the Radial_col_filter it becomes."""
    for index, wedge in enumerate(tank.filters):
        instance = emitted[f'wedge_{index}']

        def emitted_value(name):
            return expr_float(instance.get_parameter(name).value)

        assert emitted_value('angle_width') == pytest.approx(
            wedge.angle_width.to(unit='degree').value), index
        assert emitted_value('collimation') == pytest.approx(
            wedge.collimation_angle.to(unit='degree').value), index
        assert emitted_value('filter_minimum_radius') == pytest.approx(
            wedge.filter_inner_radius.to(unit='m').value), index
        assert emitted_value('collimator_minimum_radius') == pytest.approx(
            wedge.collimator_inner_radius.to(unit='m').value), index
        assert rotate_angles(instance) == pytest.approx(
            [0, wedge_angle(wedge) * 180 / 3.141592653589793, 0], abs=1e-9), index


def test_the_collimation_is_the_calibrated_one_not_the_whole_wedge(tank):
    """It used to arrive under a key nothing read.

    `RadialFilterCollimator.from_calibration` takes `collimation_angle`; the tank
    passed `collimation`, so every filter silently fell back to the default -- the
    full width of the wedge -- and the emitted instrument collimated to 7.8 degrees
    where the calibration says 0.65.
    """
    from niess.bifrost.parameters import known_channel_params
    calibrated = known_channel_params()['radial_collimator_collimation']
    for index, wedge in enumerate(tank.filters):
        assert wedge.collimation_angle.to(unit='degree').value == pytest.approx(
            calibrated.to(unit='degree').value), f'wedge_{index}'
        assert wedge.collimation_angle < wedge.angle_width


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


def test_the_wedges_tag_the_cassette_they_belong_to(tank):
    """What the radial slits used to do, and the only thing that still does it.

    Slit_radial_multi reported which opening a neutron came through and an EXTEND
    turned that index into `secondary_cassette`. The wedges carry it themselves now:
    each one is in a single GROUP, so a neutron scatters in at most one, and its
    EXTEND writes the cassette index that the channel below is gated on.
    """
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler

    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    assembler.component('sample_origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    tank.to_mccode(assembler, 'sample_origin')

    assert any('secondary_cassette' in block.source
               for block in assembler.instrument.user), 'declared as a USERVAR'

    emitted = {c.name: c for c in assembler.instrument.components}
    groups = set()
    for index in range(len(tank.filters)):
        instance = emitted[f'wedge_{index}']
        groups.add(instance.group)
        sources = ' '.join(block.source for block in instance.extend)
        assert f'secondary_cassette = {index + 1};' in sources, index

    # the monitor closes the group: a neutron that scatters in no wedge reaches it,
    # and McStas absorbs whatever fails to scatter in the last member of a GROUP
    monitor = emitted['elastic_monitor']
    groups.add(monitor.group)
    assert len(groups) == 1, 'one group, or the wedges do not exclude each other'
    assert f'secondary_cassette = {len(tank.filters) + 1};' in \
        ' '.join(block.source for block in monitor.extend)


def test_the_wedges_start_inside_everything_downstream(tank):
    """0.5 to 0.82 m for the collimators, against 1.19 m to the nearest analyzer.

    The wedges sit between the sample and the channels they tag neutrons into, which
    is what lets a neutron meet its wedge before the analyzer it is headed for. They
    have to clear it entirely, so it is the outer radius that matters.

    The elastic monitor is at 0.8 m, inside that -- but it is at 59 degrees, well
    outside the plus or minus 40 the wedges span, so the two never meet. Only the
    inner radius is comparable to it.
    """
    from scipp import concat, min as smin, max as smax, norm

    inner = smax(concat([w.collimator_inner_radius for w in tank.filters],
                        dim='wedge')).to(unit='m')
    outer = smax(concat([w.collimator_outer_radius for w in tank.filters],
                        dim='wedge')).to(unit='m')
    assert inner < outer
    assert inner < norm(tank.monitor.position).to(unit='m')
    assert outer < norm(
        tank.channels[4].pairs[0].analyzer.central_blade.position).to(unit='m')
