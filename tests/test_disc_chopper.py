"""Where a disc chopper is, and which side of the beam its spindle sits on.

A niess `DiscChopper`'s `position` is the spindle; a McStas `DiskChopper`'s origin is the
point the beam crosses the disc. Two angles say where that point is -- `zero_angle` from
the local +y axis to the disc's zero mark, `beam_angle` from the mark to the beam, both
counter-clockwise about +z -- and everything else follows from them: the vector between
the two points, and the rotation the emitted component needs so the disc ends up on the
right side of the beam.

Getting this wrong does not warn or transmit less. McStas absorbs every neutron outside
the disc radius, silently, so a chopper placed off the beam counts nothing at all.
"""
import pytest
from mccode_antlr import Flavor
from mccode_antlr.assembler import Assembler
from scipp import array, scalar, vector
from scipp.spatial import rotations_from_rotvecs

from niess.components import DiscChopper

UPRIGHT = rotations_from_rotvecs(vector([0, 0, 0.0], unit='deg'))
RADIUS, HEIGHT = 0.35, 0.06
DELTA_Y = RADIUS - HEIGHT / 2      # McStas' delta_y: the beam runs mid-slit


def calibration(**overrides):
    cal = {
        'name': 'chopper',
        'position': vector([0, 0, 5.0], unit='m'),
        'orientation': UPRIGHT,
        'radius': scalar(RADIUS, unit='m'),
        'height': scalar(HEIGHT, unit='m'),
        'angle': scalar(170.0, unit='deg'),
        'frequency': scalar(14.0, unit='Hz'),
        'delay': scalar(0.0, unit='s'),
    }
    cal.update(overrides)
    return cal


def emitted(chopper):
    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    chopper.to_mccode(assembler)
    instance = assembler.instrument.components[-1]
    return ([float(str(x)) for x in instance.at_relative[0]],
            [float(str(x)) for x in instance.rotate_relative[0]])


# -- where the beam crosses the disc ------------------------------------------

def test_the_default_angles_put_the_beam_at_the_top_of_the_disc():
    """Which is the arrangement McStas' DiskChopper already assumes.

    Its `delta_y = radius - yheight/2` sets the spindle *below* the component origin and
    it measures opening angles as `atan2(x, y + delta_y)`, zero on the beam. So a disc
    that takes the defaults needs no turning, and emits the rotation it always did.
    """
    disc = DiscChopper.from_calibration(calibration())
    assert disc.beam_offset().to(unit='m').value == pytest.approx([0.0, DELTA_Y, 0.0])
    at, rotated = emitted(disc)
    assert at == pytest.approx([0.0, DELTA_Y, 5.0])
    assert rotated == pytest.approx([0.0, 0.0, 0.0])


def test_a_disc_hanging_above_the_beam_is_half_a_turn_round():
    """The usual arrangement, and the one BIFROST has.

    The beam crosses at the bottom of the disc, so the spindle is above it and the emitted
    component turns half a turn about z -- which is what puts McStas' disc, which is
    always drawn below its own origin, above the beam instead.
    """
    disc = DiscChopper.from_calibration(
        calibration(beam_angle=scalar(180.0, unit='deg')))
    assert disc.beam_offset().to(unit='m').value == pytest.approx([0.0, -DELTA_Y, 0.0])
    at, rotated = emitted(disc)
    assert at == pytest.approx([0.0, -DELTA_Y, 5.0])
    assert rotated == pytest.approx([0.0, 0.0, 180.0])


def test_the_two_angles_add():
    """`zero_angle` reaches the mark and `beam_angle` carries on from there."""
    from math import cos, radians, sin
    disc = DiscChopper.from_calibration(calibration(
        zero_angle=scalar(30.0, unit='deg'), beam_angle=scalar(75.0, unit='deg')))
    turn = radians(105.0)
    assert disc.beam_offset().to(unit='m').value == pytest.approx(
        [-DELTA_Y * sin(turn), DELTA_Y * cos(turn), 0.0])
    assert emitted(disc)[1] == pytest.approx([0.0, 0.0, 105.0])


def test_a_disc_with_no_slit_height_is_centred_on_half_its_radius():
    """McStas takes an unset `yheight` as the full radius, so the beam runs at radius/2."""
    cal = calibration()
    cal.pop('height')
    disc = DiscChopper.from_calibration(cal)
    assert disc.beam_offset().to(unit='m').value == pytest.approx([0.0, RADIUS / 2, 0.0])


# -- one disc, however many openings ------------------------------------------

def test_a_single_opening_emits_one_component_under_the_discs_own_name():
    """Which is what a disc chopper has always been, and has to stay.

    The multi-opening machinery is now the only path, so it has to degenerate exactly:
    one instance, its own name, no GROUP, and the ordinary role -- or every existing
    instrument changes.
    """
    disc = DiscChopper.from_calibration(calibration(beam_angle=scalar(180.0, unit='deg')))
    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    instance = disc.to_mccode(assembler)

    assert not isinstance(instance, list)
    assert [c.name for c in assembler.instrument.components] == ['chopper']
    assert not instance.group
    from niess.provenance import NiessProvenance
    assert NiessProvenance.from_instance(instance).role == 'physical-component'


def test_several_openings_emit_one_component_each_in_a_group():
    disc = DiscChopper.from_calibration(calibration(
        windows=array(values=[10.0, 30.0, 100.0, 140.0], dims=['edges'], unit='deg')))
    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    instances = disc.to_mccode(assembler)

    assert [c.name for c in instances] == ['chopper_slit_0', 'chopper_slit_1']
    assert all(c.group == 'chopper_group' for c in instances)
    assert [c.get_parameter('theta_0').value for c in instances] == [20.0, 40.0]


def test_the_angle_shorthand_centres_one_opening_on_the_beam():
    """`angle` is shorthand, and the edges it produces are in the same frame as any other.

    Measured from the mark, so an opening centred on a beam half a turn round is
    `[95, 265]` rather than `[-85, 85]`. Its centre is the beam, which is what keeps the
    emitted delay the disc's own -- the shorthand has always meant "centred on the beam",
    and now it says so in the frame everything else uses.
    """
    disc = DiscChopper.from_calibration(calibration(beam_angle=scalar(180.0, unit='deg')))
    assert disc.slits() == [(95.0, 265.0)]
    assert disc._counter_clockwise_turn(95.0, 265.0) == 0.0

    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    instance = disc.to_mccode(assembler)
    assert str(instance.get_parameter('delay').value) == 'chopperdelay'
    assert 'chopper_delay' not in str(assembler.instrument)


def test_a_disc_writes_its_openings_to_nexus_in_the_mark_frame():
    """With the frame alongside them, which is what NXdisk_chopper asks for.

    A single-opening disc used to go through the bare-DiskChopper translator and write
    beam-relative edges from `theta_0`, while a multi-opening one wrote mark-relative
    ones. Both go through the same translator now.
    """
    from niess.nexus.via_instr import to_nexus_structure
    disc = DiscChopper.from_calibration(calibration(beam_angle=scalar(180.0, unit='deg')))
    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    assembler.component('origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    disc.to_mccode(assembler, at='origin', rotate='origin')

    body = next(c for c in to_nexus_structure(assembler.instrument,
                                              origin='origin')['children'][0]['children'][0]['children']
                if c.get('name') == 'chopper')
    found = {(ch.get('config') or {}).get('name'): (ch.get('config') or {}).get('values')
             for ch in body['children']}
    assert found['slit_edges'] == [95.0, 265.0]
    assert found['top_dead_center'] == 0.0
    assert found['beam_position'] == 180.0
    assert found['slit_angle'] == 170.0


# -- what NXdisk_chopper asks of the slit edges --------------------------------

def nexus_slit_edges_of(edges):
    """The `slit_edges` a disc with these `windows` writes into NeXus."""
    from niess.nexus.via_instr import to_nexus_structure
    disc = DiscChopper.from_calibration(calibration(
        windows=array(values=edges, dims=['edges'], unit='deg')))
    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    assembler.component('origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    disc.to_mccode(assembler, at='origin', rotate='origin')
    body = next(c for c in to_nexus_structure(assembler.instrument,
                                              origin='origin')['children'][0]['children'][0]['children']
                if c.get('name') == 'chopper')
    return next((ch.get('config') or {}).get('values') for ch in body['children']
                if (ch.get('config') or {}).get('name') == 'slit_edges')


@pytest.mark.parametrize('windows,expected', [
    # a slit across the mark moves to the END of the list, taking its wrap with it --
    # shifting the whole list would carry the others out past 360 with it
    ([-10.0, 10.0, 60.0, 90.0], [60.0, 90.0, 350.0, 370.0]),
    # ...including when the wrapping slit was written first
    ([350.0, 370.0, 380.0, 400.0], [20.0, 40.0, 350.0, 370.0]),
    # a slit written a turn late comes back into range
    ([370.0, 380.0], [10.0, 20.0]),
    # a lone slit across the mark is the case where the last edge may pass 360
    ([-85.0, 85.0], [275.0, 445.0]),
    # and edges that already conform are left exactly as they are
    ([10.0, 30.0, 100.0, 140.0, 350.0, 370.0], [10.0, 30.0, 100.0, 140.0, 350.0, 370.0]),
    ([95.0, 265.0], [95.0, 265.0]),
])
def test_slit_edges_are_written_as_the_standard_asks(windows, expected):
    """"The first edge must be the opening edge of a slit, thus the last edge may have an
    angle greater than 360 degrees."

    Which makes the wrap a property of one slit rather than of the list, so putting the
    edges in order means rotating which slit comes first -- not adding 360 to all of them.
    """
    assert nexus_slit_edges_of(windows) == pytest.approx(expected)


@pytest.mark.parametrize('windows', [
    [-10.0, 10.0, 60.0, 90.0], [350.0, 370.0, 380.0, 400.0], [370.0, 380.0],
    [-85.0, 85.0], [10.0, 30.0, 100.0, 140.0, 350.0, 370.0], [95.0, 265.0],
])
def test_written_slit_edges_always_satisfy_the_standard(windows):
    """The properties themselves, rather than the particular numbers."""
    written = nexus_slit_edges_of(windows)
    assert all(b > a for a, b in zip(written, written[1:]))     # strictly increasing
    assert all(0.0 <= edge < 360.0 for edge in written[:-1])    # only the last may pass
    assert written[-1] < 720.0                                  # and only by one turn


def test_pairs_survive_being_reordered():
    """Rotating the list must not split an opening from its closing edge."""
    written = nexus_slit_edges_of([-10.0, 10.0, 60.0, 90.0])
    assert [b - a for a, b in zip(written[::2], written[1::2])] == pytest.approx([30.0, 20.0])


def test_openings_that_overlap_are_refused_rather_than_written():
    """They cannot be put in the standard's order, and a disc cannot have them anyway."""
    from niess.nexus.via_instr.translators import nexus_slit_edges
    with pytest.raises(ValueError, match='overlap'):
        nexus_slit_edges([0.0, 200.0, 100.0, 300.0])


# -- the McStas frame twist stays in McStas ------------------------------------

def nexus_body(disc, name='chopper'):
    from niess.nexus.via_instr import to_nexus_structure
    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    assembler.component('origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    disc.to_mccode(assembler)
    structure = to_nexus_structure(assembler.instrument, origin='origin')
    return next(c for c in structure['children'][0]['children'][0]['children']
                if c.get('name') == name)


def nexus_rotations(body):
    return [round((t.get('config') or {}).get('values'), 9)
            for child in body['children'] if child.get('name') == 'transformations'
            for t in child['children']
            if t.get('attributes')
            and any(a.get('values') == 'rotation' for a in t['attributes'])]


def test_the_emitted_turn_is_recorded_as_provenance():
    """It is the one thing an adapter reading the instrument back cannot work out.

    The emitted ROTATED is `orientation * Rz(zero_angle + beam_angle)`, and nothing in the
    component line says which part of it is the disc and which is McStas' insistence that
    a disc hangs below its own origin.
    """
    from niess.provenance import NiessProvenance
    disc = DiscChopper.from_calibration(calibration(
        zero_angle=scalar(30.0, unit='deg'), beam_angle=scalar(75.0, unit='deg')))
    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    instance = disc.to_mccode(assembler)
    extra = NiessProvenance.from_instance(instance).extra
    assert extra['mccode_frame_rotation'] == pytest.approx([0.0, 0.0, 105.0])


def test_a_component_that_is_not_turned_records_nothing():
    """The key is absent rather than zero, so it means something when it is there."""
    from niess.provenance import NiessProvenance
    disc = DiscChopper.from_calibration(calibration())   # both angles default to zero
    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    instance = disc.to_mccode(assembler)
    assert 'mccode_frame_rotation' not in NiessProvenance.from_instance(instance).extra


def test_the_emitted_displacement_is_recorded_too():
    """The AT is moved off the spindle for the same reason the ROTATED is turned."""
    from niess.provenance import NiessProvenance
    disc = DiscChopper.from_calibration(calibration(beam_angle=scalar(180.0, unit='deg')))
    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    instance = disc.to_mccode(assembler)
    extra = NiessProvenance.from_instance(instance).extra
    assert extra['mccode_frame_offset'] == pytest.approx([0.0, -DELTA_Y, 0.0])


def test_nexus_puts_the_disc_on_its_spindle():
    """A McStas DiskChopper's origin is on the beam, because that is where its component
    expects to be. An NXdisk_chopper is centred on the disc, so the file records the
    spindle -- the point the calibration actually gave.
    """
    from niess.nexus.via_instr import to_nexus_structure
    disc = DiscChopper.from_calibration(calibration(beam_angle=scalar(180.0, unit='deg')))
    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    assembler.component('origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    instance = disc.to_mccode(assembler, at='origin', rotate='origin')

    # McStas gets the beam crossing, 0.32 m below the spindle
    assert [float(str(v)) for v in instance.at_relative[0]] == \
        pytest.approx([0.0, -DELTA_Y, 5.0], abs=1e-12)

    body = next(c for c in to_nexus_structure(assembler.instrument,
                                              origin='origin')['children'][0]['children'][0]['children']
                if c.get('name') == 'chopper')
    placed = {(t.get('config') or {}).get('name'): (t.get('config') or {}).get('values')
              for ch in body['children'] if ch.get('name') == 'transformations'
              for t in ch['children']}
    assert [placed.get(f'chopper_t0_{k}', 0.0) for k in 'xyz'] == \
        pytest.approx([0.0, 0.0, 5.0], abs=1e-12)


def test_the_spindle_is_recovered_against_a_rotated_reference():
    """Where a naive subtraction would go wrong.

    The displacement is added to the position in whatever frame the component was placed
    against, so it has to come back out of the same quantity -- not out of a resolved
    absolute position, which a rotated reference has already turned.
    """
    from niess.nexus.via_instr import to_nexus_structure
    tilt = rotations_from_rotvecs(vector(value=[0.0, 37.0, 0.0], unit='deg'))
    disc = DiscChopper.from_calibration(calibration(
        orientation=tilt, beam_angle=scalar(180.0, unit='deg')))
    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    assembler.component('ref', 'Arm', at=((1., 2., 3.), 'ABSOLUTE'),
                        rotate=((0., 20., 0.), 'ABSOLUTE'))
    disc.to_mccode(assembler, at='ref', rotate='ref')

    body = next(c for c in to_nexus_structure(assembler.instrument,
                                              origin='ref')['children'][0]['children'][0]['children']
                if c.get('name') == 'chopper')
    placed = {(t.get('config') or {}).get('name'): (t.get('config') or {}).get('values')
              for ch in body['children'] if ch.get('name') == 'transformations'
              for t in ch['children']}
    # the spindle, in the reference's frame, exactly as the calibration gave it
    assert [placed.get(f'chopper_t0_{k}', 0.0) for k in 'xyz'] == \
        pytest.approx([0.0, 0.0, 5.0], abs=1e-12)


def test_nexus_records_the_discs_own_orientation():
    """Not the turned one it is emitted with.

    A disc whose calibration says it is not rotated at all must not arrive in the file
    rotated by 105 degrees, which is what `zero_angle + beam_angle` puts into the emitted
    component. 105 is chosen because no sign error or axis swap maps it onto itself.
    """
    disc = DiscChopper.from_calibration(calibration(
        angle=scalar(20.0, unit='deg'),   # narrow, so its edges need no wrapping
        zero_angle=scalar(30.0, unit='deg'), beam_angle=scalar(75.0, unit='deg')))
    # the emitted component really does carry the turn
    assert emitted(disc)[1] == pytest.approx([0.0, 0.0, 105.0])
    # and the file does not
    body = nexus_body(disc)
    assert nexus_rotations(body) == []
    found = {(ch.get('config') or {}).get('name'): (ch.get('config') or {}).get('values')
             for ch in body['children']}
    assert found['top_dead_center'] == 30.0
    assert found['beam_position'] == 75.0
    assert found['slit_edges'] == [65.0, 85.0]


def test_a_turned_disc_matches_a_component_placed_where_it_really_is():
    """The strongest form of the check: same rotation chain as an untwisted stand-in."""
    from niess.nexus.via_instr import to_nexus_structure
    from niess.spatial import mccode_ordered_angles
    tilt = rotations_from_rotvecs(vector(value=[0.0, -12.5, 0.0], unit='deg'))
    disc = DiscChopper.from_calibration(calibration(
        orientation=tilt, beam_angle=scalar(180.0, unit='deg')))

    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    assembler.component('origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    disc.to_mccode(assembler)
    # a stand-in at the same point, carrying the disc's physical orientation
    assembler.component(
        'reference', 'Arm',
        at=(tuple((disc.position + disc.beam_offset()).to(unit='m').value), 'ABSOLUTE'),
        rotate=(tuple(mccode_ordered_angles(tilt)), 'ABSOLUTE'))

    structure = to_nexus_structure(assembler.instrument, origin='origin')
    kids = {c.get('name'): c for c in structure['children'][0]['children'][0]['children']}
    assert nexus_rotations(kids['chopper']) == nexus_rotations(kids['reference'])
    assert nexus_rotations(kids['chopper']) != []      # or the comparison is vacuous


def test_every_opening_of_a_split_disc_is_untwisted():
    """Each instance carries the same turn, so each has to have it taken back out."""
    disc = DiscChopper.from_calibration(calibration(
        beam_angle=scalar(180.0, unit='deg'),
        windows=array(values=[95.0, 115.0, 245.0, 265.0], dims=['edges'], unit='deg')))
    from niess.nexus.via_instr import to_nexus_structure
    assembler = Assembler('chopped', flavor=Flavor.MCSTAS)
    assembler.component('origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    instances = disc.to_mccode(assembler)
    assert len(instances) == 2
    structure = to_nexus_structure(assembler.instrument, origin='origin')
    body = next(c for c in structure['children'][0]['children'][0]['children']
                if c.get('name') == 'chopper')
    assert nexus_rotations(body) == []


# -- the angles are the only description --------------------------------------

def test_the_angles_are_enough_to_place_the_disc():
    """There is no offset to give: the vector is derived, every time it is needed."""
    disc = DiscChopper.from_calibration(calibration(beam_angle=scalar(180.0, unit='deg')))
    assert not hasattr(disc, 'offset')
    assert emitted(disc)[0] == pytest.approx([0.0, -DELTA_Y, 5.0])


def test_a_calibration_that_still_gives_an_offset_is_refused():
    """Rather than ignored, which would move the disc without saying so.

    An offset used to be accepted and checked against the angles. Taking it away silently
    would leave a calibration that meant one thing being read as another -- and a disc
    chopper off the beam absorbs every neutron without complaining -- so it is an error
    with the migration in it.
    """
    with pytest.raises(ValueError, match='placed by where the beam crosses it'):
        DiscChopper.from_calibration(
            calibration(offset=vector([0, -DELTA_Y, 0], unit='m'),
                        beam_angle=scalar(180.0, unit='deg')))


def test_the_derived_offset_follows_an_edited_radius():
    """Which a stored vector could not do, and is why this is not a field.

    Its length is `radius - height/2`, McStas' rule for centring the beam in the slit --
    a fact about the emitted component, not about the chopper, and one that goes stale
    the moment either number changes.
    """
    disc = DiscChopper.from_calibration(calibration(beam_angle=scalar(180.0, unit='deg')))
    disc.radius = scalar(0.5, unit='m')
    assert disc.beam_offset().to(unit='m').value == pytest.approx(
        [0.0, -(0.5 - HEIGHT / 2), 0.0])


# -- the names the calibration may use ----------------------------------------

def test_the_nexus_names_are_accepted():
    """`top_dead_center` and `beam_position` are what NXdisk_chopper calls these."""
    disc = DiscChopper.from_calibration(calibration(
        top_dead_center=scalar(30.0, unit='deg'),
        beam_position=scalar(75.0, unit='deg')))
    assert disc.zero_angle.to(unit='deg').value == pytest.approx(30.0)
    assert disc.beam_angle.to(unit='deg').value == pytest.approx(75.0)


def test_reading_a_calibration_does_not_change_it():
    """Calibrations are reused across builds, so a build must not write back into one."""
    cal = calibration(top_dead_center=scalar(30.0, unit='deg'))
    before = dict(cal)
    DiscChopper.from_calibration(cal)
    assert cal == before
    assert 'zero_angle' not in cal


# -- the instrument this is for -----------------------------------------------

def test_every_bifrost_chopper_lands_on_the_beam():
    """And its spindle above, which is where BIFROST's discs actually hang.

    The emitted rotation used to be missing the half turn, so McStas put every disc below
    the beam and ran them through the top -- a mirror image of the real instrument.
    """
    from niess.bifrost import Primary
    from niess.components import DiscChopper as Disc

    def discs(section, prefix=''):
        for name, kind in section.items():
            member = getattr(section, name)
            if isinstance(member, Disc):
                yield f'{prefix}{name}', member
            elif hasattr(member, 'items'):
                yield from discs(member, f'{prefix}{name}.')

    found = dict(discs(Primary.from_calibration()))
    assert len(found) == 6
    for name, disc in found.items():
        assert disc.beam_angle.to(unit='deg').value == pytest.approx(180.0), name
        # the spindle is above the beam, and the emitted AT is on it
        assert disc.position.fields.y.to(unit='m').value > 0, name
        assert (disc.position + disc.beam_offset()).fields.y.to(unit='m').value == \
            pytest.approx(0.0, abs=1e-9), name


def test_bifrost_no_longer_says_its_offsets():
    """The calibration states where the beam crosses; the vector follows.

    Each of BIFROST's six discs used to carry `offset` as a hand-written
    `-(radius - height/2) * y`, repeated across three files and agreeing with the angles
    only by luck. `beam_angle = 180` says the same thing once.
    """
    from niess.bifrost import Primary
    from niess.components import DiscChopper as Disc

    def discs(section):
        for name, kind in section.items():
            member = getattr(section, name)
            if isinstance(member, Disc):
                yield member
            elif hasattr(member, 'items'):
                yield from discs(member)

    found = list(discs(Primary.from_calibration()))
    assert len(found) == 6
    for disc in found:
        radial = disc.radius - disc.height / 2
        assert disc.beam_offset().to(unit='m').value == pytest.approx(
            [0.0, -radial.to(unit='m').value, 0.0], abs=1e-12)
