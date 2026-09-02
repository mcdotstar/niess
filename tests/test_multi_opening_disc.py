"""A disc with unevenly spaced openings, emitted as several components.

McStas' ``DiskChopper`` describes ``nslit`` identical, evenly spaced openings, so a disc
with neither has to be emitted as one ``DiskChopper`` per opening -- which is what
``DiscChopper.__mccode__`` refuses to do and points at instead. ``DiscChopper`` does it,
and tags the instances so anything reading the emitted file can tell they are one disc.

Putting them back together was a thing the instrument-reading NeXus route had to do.
Nothing in niess does it now: the tree never split the disc, so `niess.nexus` writes one
`NXdisk_chopper` from the one `DiscChopper` that was always there. What is left here is
the McStas half -- that the emission is right -- which is as load-bearing as it ever was.
"""
import pytest
from mccode_antlr import Flavor
from mccode_antlr.assembler import Assembler
from scipp import array, scalar, vector
from scipp.spatial import rotations_from_rotvecs

from niess.components import DiscChopper
from niess.provenance import NiessProvenance

# Angles from the top-dead-centre mark, positive counter-clockwise facing +z, as
# NXdisk_chopper wants them. The last opening straddles the mark, so it closes beyond
# 360 rather than wrapping to a smaller number.
EDGES = [10.0, 30.0, 100.0, 140.0, 350.0, 370.0]
BEAM_POSITION = 90.0


def calibration(**overrides):
    cal = {
        'name': 'pack',
        'position': vector([0, 0, 5.0], unit='m'),
        'orientation': rotations_from_rotvecs(vector([0, 0, 0.0], unit='deg')),
        'radius': scalar(0.35, unit='m'),
        'height': scalar(0.06, unit='m'),
        'frequency': scalar(14.0, unit='Hz'),
        'windows': array(values=EDGES, dims=['edges'], unit='deg'),
        'top_dead_center': scalar(15.0, unit='deg'),
        'beam_position': scalar(BEAM_POSITION, unit='deg'),
    }
    cal.update(overrides)
    return cal


@pytest.fixture
def assembled():
    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    assembler.component('origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    DiscChopper.from_calibration(calibration()).to_mccode(
        assembler, at='origin', rotate='origin')
    assembler.component('sample', 'Arm', at=((0, 0, 8), 'origin'))
    return assembler.instrument


def instances(instrument):
    """The DiskChopper instances the disc emitted, however many that is.

    A disc with several openings emits `pack_slit_N` apiece; one with a single opening
    emits `pack` itself, which is what a disc chopper has always been.
    """
    return [c for c in instrument.components
            if c.name == 'pack' or c.name.startswith('pack_slit_')]


# -- what it emits -----------------------------------------------------------

def test_one_component_per_opening(assembled):
    assert [c.name for c in assembled.components] == [
        'origin', 'pack_slit_0', 'pack_slit_1', 'pack_slit_2', 'sample',
    ]
    assert all(c.type.name == 'DiskChopper' for c in instances(assembled))


def test_each_opening_carries_its_own_width(assembled):
    widths = [float(str(c.get_parameter('theta_0').value)) for c in instances(assembled)]
    assert widths == [20.0, 40.0, 20.0]


def test_each_opening_turns_to_the_beam_from_where_it_sits(assembled):
    """McStas delay is when an opening's centre is at the beam.

    Openings are centred at 20, 120 and 360 degrees from the mark; the beam sits at 90,
    so the disc turns through the difference, wrapped into one revolution. Each opening
    reads its own start-up variable rather than a number, because how long that turn
    takes is not known until the disc has a speed.
    """
    delays = [str(c.get_parameter('delay').value) for c in instances(assembled)]
    assert delays == ['pack_slit_0_delay', 'pack_slit_1_delay', 'pack_slit_2_delay']


def test_which_way_the_disc_turns_is_decided_at_run_time(assembled):
    """Speed is a run-time parameter, so its sign cannot be baked in here.

    An opening 70 degrees counter-clockwise of the beam is 290 degrees clockwise of it,
    and a disc reaches it the way it happens to be turning. Both angles are geometry, so
    both are computed here; picking between them needs the speed, so the generated C
    does that -- along with dividing by a magnitude that is equally unknown.
    """
    text = str(assembled)
    assert 'double pack_slit_0_delay;' in text
    assert ('pack_slit_0_delay = packdelay '
            '+ (packspeed < 0 ? 290.0 : 70.0) / (360.0 * fabs(packspeed));') in text
    # 330 counter-clockwise is 30 the other way; 90 is 270
    assert '(packspeed < 0 ? 30.0 : 330.0)' in text
    assert '(packspeed < 0 ? 270.0 : 90.0)' in text


def test_an_opening_already_at_the_beam_needs_no_variable():
    """It is at the beam at the disc's own delay however the disc turns."""
    cal = calibration(windows=array(values=[80.0, 100.0], dims=['edges'], unit='deg'))
    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    assembler.component('origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    DiscChopper.from_calibration(cal).to_mccode(
        assembler, at='origin', rotate='origin')

    only = instances(assembler.instrument)[0]
    assert str(only.get_parameter('delay').value) == 'packdelay'
    assert 'pack_slit_0_delay' not in str(assembler.instrument)


def test_every_opening_is_in_one_group(assembled):
    """A neutron passes the disc if it clears *any* opening.

    Ungrouped, each DiskChopper absorbs whatever misses its own slit, so a neutron
    would have to be inside all three openings at once to survive -- the instrument
    would transmit essentially nothing. McStas GROUP is what makes them alternatives
    rather than a series.
    """
    groups = {c.group for c in instances(assembled)}
    assert groups == {'pack_group'}
    assert 'GROUP pack_group' in str(assembled)


def test_the_group_name_follows_the_disc_name():
    """Instance names are unique in an instrument, so a name-derived group is too."""
    chopper = DiscChopper.from_calibration(calibration(name='second_pack'))
    assert chopper.group_name() == 'second_pack_group'


def test_two_discs_do_not_share_a_group():
    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    assembler.component('origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    for name in ('first', 'second'):
        DiscChopper.from_calibration(calibration(name=name)).to_mccode(
            assembler, at='origin', rotate='origin')

    groups = {c.name: c.group for c in assembler.instrument.components
              if 'slit' in c.name}
    assert set(groups.values()) == {'first_group', 'second_group'}
    assert groups['first_slit_0'] != groups['second_slit_0']


def test_the_disc_has_one_speed_and_one_delay(assembled):
    """One physical disc, so one pair of run-time parameters -- not one per opening."""
    assert sorted(p.name for p in assembled.parameters) == ['packdelay', 'packspeed']
    assert all(str(c.get_parameter('nu').value) == 'packspeed'
               for c in instances(assembled))


@pytest.mark.parametrize('edges,message', [
    ([0.0, 10.0, 20.0], 'even number'),
    ([30.0, 10.0], 'strictly increase'),
    ([10.0, 10.0], 'strictly increase'),
    ([10.0, 20.0, 100.0, 380.0], 'overlap themselves'),
], ids=['odd', 'decreasing', 'repeated', 'overlapping'])
def test_edges_must_follow_the_convention(edges, message):
    cal = calibration(windows=array(values=edges, dims=['edges'], unit='deg'))
    with pytest.raises(ValueError, match=message):
        DiscChopper.from_calibration(cal).slits()


@pytest.mark.parametrize('edges,ids', [
    ([-5.0, 5.0], 'an opening across the mark'),
    ([370.0, 380.0], 'an opening described a turn later'),
])
def test_edges_need_not_be_positive(edges, ids):
    """The `NXdisk_chopper` convention wants positive edges; the component does not.

    An opening centred on a beam at `beam_angle = 0` straddles the mark, and `[-85, 85]`
    says that more plainly than `[275, 445]`. Nothing downstream cares -- a disc reaches
    the same place every turn -- and the NeXus writer shifts them into `[0, 360)`, where
    the convention is what applies.
    """
    cal = calibration(windows=array(values=edges, dims=['edges'], unit='deg'))
    assert DiscChopper.from_calibration(cal).slits() == [(edges[0], edges[1])]


def test_openings_may_just_touch():
    """A last edge exactly 360 beyond the first closes where the first opens."""
    cal = calibration(windows=array(values=[10.0, 30.0, 350.0, 370.0],
                                    dims=['edges'], unit='deg'))
    assert DiscChopper.from_calibration(cal).slits() == [
        (10.0, 30.0), (350.0, 370.0),
    ]


def test_a_straddling_opening_keeps_its_edge_beyond_360(assembled):
    """[350, 370] rather than [350, 10]: the pairs stay ordered and widths stay simple."""
    from niess.provenance import NiessProvenance as P

    last = instances(assembled)[-1]
    assert P.from_instance(last).extra['slit_edges'] == [350.0, 370.0]
    assert float(str(last.get_parameter('theta_0').value)) == 20.0


def test_the_beam_crossing_moves_the_whole_disc(assembled):
    """Every opening is one disc, so the beam crosses all of them in the same place."""
    # 0.32 m below the spindle: `radius - height/2`, half a turn from the zero mark
    cal = calibration(zero_angle=scalar(0.0, unit='deg'),
                      beam_angle=scalar(180.0, unit='deg'))
    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    assembler.component('origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    DiscChopper.from_calibration(cal).to_mccode(
        assembler, at='origin', rotate='origin')

    for instance in instances(assembler.instrument):
        # compared as numbers: the derived vector carries sin(180 deg) worth of x, which
        # is 4e-17 m and is not worth pretending is a zero in the emitted text
        assert [float(str(x)) for x in instance.at_relative[0]] == \
            pytest.approx([0.0, -0.32, 5.0], abs=1e-12)


def test_a_calibration_that_still_gives_an_offset_is_refused():
    """A disc is placed by where the beam crosses it, and only by that."""
    cal = calibration(offset=vector([0, -0.32, 0], unit='m'))
    with pytest.raises(ValueError, match='placed by where the beam crosses it'):
        DiscChopper.from_calibration(cal)


def test_the_offset_can_be_left_to_the_angles():
    """Saying where the beam crosses the disc is enough to place it.

    Both angles count, and they add: the mark sits 15 degrees from +y and the beam half a
    turn from the mark, so the beam crosses 195 degrees round -- at radius 0.32 m, which
    is `radius - height/2`, McStas' rule for centring the beam in the slit.
    """
    from math import cos, radians, sin
    cal = calibration(beam_angle=scalar(180.0, unit='deg'))   # zero_angle stays at 15
    cal.pop('offset', None)
    disc = DiscChopper.from_calibration(cal)

    turn = radians(15.0 + 180.0)
    assert disc.beam_offset().to(unit='m').value == pytest.approx(
        [-0.32 * sin(turn), 0.32 * cos(turn), 0.0])


# -- what it records ---------------------------------------------------------

def test_every_instance_is_tagged_as_one_group(assembled):
    provenances = [NiessProvenance.from_instance(c) for c in instances(assembled)]

    assert all(p is not None for p in provenances)
    assert {p.extra['disc_group_id'] for p in provenances} == {'pack'}
    assert [p.extra['disc_group_index'] for p in provenances] == [0, 1, 2]
    assert [p.extra['slit_edges'] for p in provenances] == [
        [10.0, 30.0], [100.0, 140.0], [350.0, 370.0],
    ]
    assert {p.extra['top_dead_center'] for p in provenances} == {15.0}
    assert {p.extra['beam_position'] for p in provenances} == {BEAM_POSITION}


def test_exactly_one_instance_is_the_primary(assembled):
    roles = [NiessProvenance.from_instance(c).role for c in instances(assembled)]
    assert roles.count('disc-opening-primary') == 1
    assert roles == ['disc-opening-primary'] + ['disc-opening-member'] * 2


def test_tagging_can_be_declined(assembled):
    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    assembler.component('origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    DiscChopper.from_calibration(calibration()).to_mccode(
        assembler, at='origin', rotate='origin', insert_provenance_metadata=False)

    assert all(NiessProvenance.from_instance(c) is None
               for c in instances(assembler.instrument))


# -- what it converts to -----------------------------------------------------











