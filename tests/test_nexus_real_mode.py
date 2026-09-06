"""One instrument tree, two files: a simulated run and a real one.

A simulated instrument reads its driven axes off McCode parameter names; a real one
reads EPICS positioners, which ESS spells as three logs off one PV root -- `{root}.RBV`
as `value`, `{root}.VAL` as `target_value`, `{root}.DMOV` as `idle_flag`. Nothing about
the instrument changes between the two, so the tree carries the roots and the
conversion decides whether to use them.

The group is the same shape either way. A simulation has no setpoint and no done flag
-- the parameter *is* the position -- so it writes `value` alone, and the ESS layout
check says so as a warning. That is a true statement about a simulated file, not a
defect in it.
"""
import pytest
from scipp import scalar, vector
from scipp.spatial import rotations_from_rotvecs

from niess.instrument import Instrument, Mount
from niess.nexus import REAL, SIMULATED, RealStreams, UndeclaredAxis, to_nexus_structure
from niess.nexus.nodes import children_of, find_child, get_attribute

ROOTS = {'left': 'BIFROST-SlitSy:MC-SltH-01:LftJaw',
         'right': 'BIFROST-SlitSy:MC-SltH-01:RgtJaw'}


def instrument_group(structure):
    return structure['children'][0]['children'][0]


def value(node, name):
    return find_child(node, name)['config']['values']


def f144(log):
    """The one stream module filling an NXlog."""
    return log['children'][0]


def log_names(node):
    """The NXlog children, which is what the ESS layout check looks at.

    NXlogs only: a disc also carries an `NXtransformations` group, and the check ignores
    anything that is not a log.
    """
    return [c['name'] for c in children_of(node)
            if c.get('type') == 'group' and get_attribute(c, 'NX_class') == 'NXlog']


def jawed(pv_roots=None, position=vector([0, 0, 5.0], unit='m')):
    """One jaw, driven at both edges."""
    from niess.components import Section
    from niess.components.aperture import Jaw

    cal = {'name': 'jaw', 'position': position,
           'orientation': rotations_from_rotvecs(vector([0, 0, 0.0], unit='deg')),
           'width': scalar(0.03, unit='m'), 'height': scalar(0.05, unit='m')}
    if pv_roots is not None:
        cal['pv_roots'] = pv_roots

    class Jawed(Section):
        jaw: Jaw
        _flat: bool = True

    return Instrument(name='jawed', parts=(Mount(name='m', content=Jawed(jaw=Jaw.from_calibration(cal))),))


def emitted_jaw(instrument, streams=None):
    return find_child(instrument_group(to_nexus_structure(instrument, streams=streams)), 'jaw')


# -- a driven edge -------------------------------------------------------------

def test_a_simulated_edge_is_a_positioner_with_one_log():
    """No setpoint and no done flag in a simulation: the parameter is the position."""
    left = find_child(emitted_jaw(jawed()), 'left')
    assert get_attribute(left, 'NX_class') == 'NXpositioner'
    assert log_names(left) == ['value']
    assert f144(find_child(left, 'value'))['config']['source'] == 'jaw_l'


def test_a_real_edge_is_the_ess_canonical_positioner():
    left = find_child(emitted_jaw(jawed(ROOTS), streams=REAL), 'left')
    assert log_names(left) == ['value', 'target_value', 'idle_flag']
    root = ROOTS['left']
    assert [f144(find_child(left, n))['config']['source'] for n in log_names(left)] \
        == [f'{root}.RBV', f'{root}.VAL', f'{root}.DMOV']


def test_the_idle_flag_is_an_integer_with_no_units():
    """What the template declares, and the empty string must be written, not omitted."""
    left = find_child(emitted_jaw(jawed(ROOTS), streams=REAL), 'left')
    idle = f144(find_child(left, 'idle_flag'))['config']
    assert idle['dtype'] == 'int64'
    assert idle['value_units'] == ''
    assert not (find_child(left, 'idle_flag')['children'][0].get('attributes') or [])


def test_value_and_target_value_agree_on_dtype_and_units():
    """The compiler cannot infer a PV root from logs that disagree."""
    left = find_child(emitted_jaw(jawed(ROOTS), streams=REAL), 'left')
    configs = [f144(find_child(left, n))['config'] for n in ('value', 'target_value')]
    assert len({c['dtype'] for c in configs}) == 1
    assert len({c['value_units'] for c in configs}) == 1
    assert len({c['topic'] for c in configs}) == 1


# -- the units, both of them ----------------------------------------------------

def test_every_f144_names_its_value_units():
    """`unit` is not a key the ESS f144 contract declares; `value_units` is."""
    for streams in (SIMULATED, REAL):
        jaw = emitted_jaw(jawed(ROOTS), streams=streams)
        for edge in ('left', 'right'):
            for log in children_of(find_child(jaw, edge)):
                if log.get('type') != 'group':
                    continue
                config = f144(log)['config']
                assert 'value_units' in config, (streams, edge, log['name'])
                assert 'unit' not in config, (streams, edge, log['name'])


def test_no_unit_arrives_still_quoted():
    """`InstrumentParameter.unit` is the four characters `"m"`. A NeXus unit is `m`."""
    left = find_child(emitted_jaw(jawed(ROOTS), streams=REAL), 'left')
    module = f144(find_child(left, 'value'))
    assert module['config']['value_units'] == 'm'
    attrs = {a['name']: a['values'] for a in module['attributes']}
    assert attrs['units'] == 'm'


def test_the_units_attribute_and_value_units_cannot_disagree():
    """A resolver reads the attribute first; the config is the transport contract.

    Cleaning one and not the other is how a silently wrong unit becomes a loudly
    conflicting one, so both are written from a single string.
    """
    left = find_child(emitted_jaw(jawed(ROOTS), streams=REAL), 'left')
    for name in ('value', 'target_value'):
        module = f144(find_child(left, name))
        attrs = {a['name']: a['values'] for a in (module.get('attributes') or [])}
        assert attrs['units'] == module['config']['value_units'], name


# -- an axis nobody wired up ----------------------------------------------------

def test_a_real_conversion_says_so_when_an_axis_has_no_pv():
    """Silence here would put a plausible simulated axis inside a file claiming to be real."""
    with pytest.raises(UndeclaredAxis, match='jaw_l'):
        to_nexus_structure(jawed(), streams=REAL)


def test_a_half_wired_instrument_can_ask_for_the_rest_simulated():
    jaw = emitted_jaw(jawed({'left': ROOTS['left']}), streams=RealStreams(strict=False))
    assert log_names(find_child(jaw, 'left')) == ['value', 'target_value', 'idle_flag']
    assert log_names(find_child(jaw, 'right')) == ['value']


# -- one tree, two files --------------------------------------------------------

def test_the_same_tree_gives_both_files():
    """The requirement itself. Only the positioners differ."""
    instrument = jawed(ROOTS)
    sim = instrument_group(to_nexus_structure(instrument, streams=SIMULATED))
    real = instrument_group(to_nexus_structure(instrument, streams=REAL))

    def shape(node):
        return [(c.get('name'), get_attribute(c, 'NX_class'))
                for c in children_of(node) if c.get('type') == 'group']

    assert shape(sim) == shape(real)
    assert shape(find_child(sim, 'jaw')) == shape(find_child(real, 'jaw'))


def test_declaring_pv_roots_does_not_change_the_mccode():
    """The tree stays a simulation instrument however much control-system detail it carries."""
    from niess.mccode import to_mccode
    assert str(to_mccode(jawed(ROOTS))) == str(to_mccode(jawed()))


# -- a motorised frame ----------------------------------------------------------
#
# `NXcomponent` does not accept an `NXpositioner` child and `NXinstrument` does, so a
# motorised frame's positioner sits beside the frame rather than inside it. The chain
# threads through it: the positioner's `value` carries the transformation attributes,
# and whatever hangs off the frame names that `value`.

def turned(pv_root=None, name='a4'):
    """One component on a mounting turned by a motor."""
    from niess.components import Section
    from niess.components.component import Component
    from niess.components.motor import Motor

    motor = Motor(name=name, unit='degree', source=name, topic='motion',
                  default=0.0, pv_root=pv_root)
    thing = Component(name='thing', position=vector([0, 0, 2.0], unit='m'),
                      orientation=rotations_from_rotvecs(vector([0, 0, 0.0], unit='deg')))

    class Held(Section):
        thing: Component
        _flat: bool = True

    return Instrument(name='turned', parts=(
        Mount(name='tank', rotation=(0, motor, 0), content=Held(thing=thing)),))


def test_a_motorised_frame_is_a_positioner_beside_it():
    group = instrument_group(to_nexus_structure(turned('BF:Rot-01'), streams=REAL))
    positioner = find_child(group, 'tank_mounting_a4')
    assert get_attribute(positioner, 'NX_class') == 'NXpositioner'
    assert log_names(positioner) == ['value', 'target_value', 'idle_flag']


def test_the_frame_keeps_no_transformation_for_that_axis():
    """Two names for one number, and the copy is the one readers would trust."""
    group = instrument_group(to_nexus_structure(turned('BF:Rot-01'), streams=REAL))
    frame = find_child(group, 'tank_mounting')
    assert find_child(frame, 'transformations') is None
    assert value(frame, 'depends_on') == '/entry/instrument/tank_mounting_a4/value'


def test_the_transformation_rides_on_the_value_log():
    group = instrument_group(to_nexus_structure(turned('BF:Rot-01'), streams=REAL))
    log = find_child(find_child(group, 'tank_mounting_a4'), 'value')
    attrs = {a['name']: a['values'] for a in log['attributes']}
    assert attrs['transformation_type'] == 'rotation'
    assert attrs['vector'] == [0.0, 1.0, 0.0]
    # units belong to the values, and the values live in the module
    assert 'units' not in attrs
    assert {a['name'] for a in f144(log)['attributes']} == {'units'}


def test_the_chain_threads_through_the_positioner():
    """What hangs off the frame must name the positioner, not the frame."""
    group = instrument_group(to_nexus_structure(turned('BF:Rot-01'), streams=REAL))
    rotation = find_child(find_child(group, 'thing'), 'transformations')
    translation = find_child(rotation, 'translation')
    assert get_attribute(translation, 'depends_on') == \
        '/entry/instrument/tank_mounting_a4/value'


def test_a_simulated_frame_is_the_same_shape():
    """Same groups, same depends_on targets; only the sources and log count differ."""
    group = instrument_group(to_nexus_structure(turned(), streams=SIMULATED))
    positioner = find_child(group, 'tank_mounting_a4')
    assert log_names(positioner) == ['value']
    assert f144(find_child(positioner, 'value'))['config']['source'] == 'a4'
    assert value(find_child(group, 'tank_mounting'), 'depends_on') == \
        '/entry/instrument/tank_mounting_a4/value'


def test_two_frames_turned_by_one_named_knob_get_two_positioners():
    """They cannot share one: the chain each hangs from differs."""
    from niess.components import Section
    from niess.components.component import Component
    from niess.components.motor import Motor

    motor = Motor(name='a4', unit='degree', source='a4', topic='motion', default=0.0)
    def held(label):
        thing = Component(name=label, position=vector([0, 0, 2.0], unit='m'),
                          orientation=rotations_from_rotvecs(vector([0, 0, 0.0], unit='deg')))
        class Held(Section):
            thing: Component
            _flat: bool = True
        return Held(thing=thing)

    instrument = Instrument(name='two', parts=(
        Mount(name='one', rotation=(0, motor, 0), content=held('a')),
        Mount(name='two', rotation=(0, motor, 0), content=held('b')),
    ))
    group = instrument_group(to_nexus_structure(instrument))
    assert find_child(group, 'one_mounting_a4') is not None
    assert find_child(group, 'two_mounting_a4') is not None


# -- a disc chopper -------------------------------------------------------------
#
# ESS spells a chopper as eight stream-fed logs off one controller. A simulation has
# four of those quantities at best, and the validator can only offer to fix a group it
# can infer a PV root for -- which it does from the top_dead_center source, so a group
# without one cannot even be diagnosed properly.

CHOPPER_ROOT = 'BIFRO-ChpSy1:Chop-PSC-101'


def chopped(pv_root=None, tdc_channel='00-TS-I'):
    from niess.components import Section
    from niess.components.chopper import DiscChopper

    cal = {'name': 'psc1', 'position': vector([0, 0, 4.4], unit='m'),
           'orientation': rotations_from_rotvecs(vector([0, 0, 0.0], unit='deg')),
           'radius': scalar(0.35, unit='m'), 'height': scalar(0.06, unit='m'),
           'angle': scalar(170., unit='deg'), 'frequency': scalar(14., unit='Hz'),
           'delay': scalar(0., unit='s'), 'beam_angle': scalar(180., unit='deg')}
    if pv_root is not None:
        cal |= {'pv_root': pv_root, 'tdc_channel': tdc_channel}

    class Chopped(Section):
        disc: DiscChopper
        _flat: bool = True

    return Instrument(name='chopped',
                      parts=(Mount(name='m', content=Chopped(disc=DiscChopper.from_calibration(cal))),))


def emitted_disc(instrument, streams=None):
    return find_child(instrument_group(to_nexus_structure(instrument, streams=streams)), 'psc1')


def stream_of(log):
    c = log['children'][0]
    return c['module'], c['config']['source']


CANONICAL = ['rotation_speed', 'rotation_speed_setpoint', 'top_dead_center', 'delay',
             'experiment_delay', 'mechanical_delay', 'pulse_delay', 'park_angle']


def test_a_real_disc_is_the_ess_canonical_eight():
    """In this order: the layout check compares the name list exactly."""
    disc = emitted_disc(chopped(CHOPPER_ROOT), streams=REAL)
    assert log_names(disc) == CANONICAL


def test_the_top_dead_centre_log_is_a_tdct_stream():
    """Not f144. It is a vector of absolute times, and it is what lets the validator
    recover the PV root -- the suffix is per-chopper, so it cannot be guessed."""
    disc = emitted_disc(chopped(CHOPPER_ROOT, tdc_channel='02-TS-I'), streams=REAL)
    module, source = stream_of(find_child(disc, 'top_dead_center'))
    assert module == 'tdct'
    assert source == f'{CHOPPER_ROOT}:02-TS-I'
    config = find_child(disc, 'top_dead_center')['children'][0]['config']
    assert set(config) == {'source', 'topic'}     # tdct declares no dtype, no units
    attrs = {a['name']: a['values'] for a in find_child(disc, 'top_dead_center')['attributes']}
    assert attrs['default'] == 'time'


def test_the_seven_f144_logs_hang_off_one_root():
    disc = emitted_disc(chopped(CHOPPER_ROOT), streams=REAL)
    for name in CANONICAL:
        module, source = stream_of(find_child(disc, name))
        assert source.startswith(CHOPPER_ROOT), name
        assert module == ('tdct' if name == 'top_dead_center' else 'f144'), name


def test_a_simulated_disc_says_only_what_it_knows():
    """No setpoint distinct from the value, and no electronics to delay anything."""
    disc = emitted_disc(chopped())
    assert log_names(disc) == ['rotation_speed', 'top_dead_center', 'mark_delay', 'park_angle']
    assert stream_of(find_child(disc, 'rotation_speed'))[1] == 'psc1speed'


def test_the_mccode_delay_is_never_written_as_the_ess_delay():
    """ESS `delay` is the controller's total electronic delay, in nanoseconds. The
    McStas one is when the disc's mark reaches the beam, in seconds. Writing the second
    under the first's name would be read as the first by everything downstream.
    """
    disc = emitted_disc(chopped())
    assert find_child(disc, 'delay') is None
    mark = find_child(disc, 'mark_delay')
    assert stream_of(mark)[1] == 'psc1delay'
    assert mark['children'][0]['config']['value_units'] == 's'


def test_a_declared_root_is_ignored_when_simulating():
    """A simulated file naming real PVs would claim values nothing published."""
    disc = emitted_disc(chopped(CHOPPER_ROOT), streams=SIMULATED)
    assert log_names(disc) == ['rotation_speed', 'top_dead_center', 'mark_delay', 'park_angle']
    assert CHOPPER_ROOT not in str(disc)


def test_a_real_conversion_says_so_when_a_disc_has_no_controller():
    with pytest.raises(UndeclaredAxis, match='psc1'):
        to_nexus_structure(chopped(), streams=REAL)


# -- the pulse reference times ---------------------------------------------------

def test_the_instrument_records_where_its_timestamps_are_measured_from():
    """Without these a top-dead-centre time cannot be used at all."""
    inst = instrument_group(to_nexus_structure(chopped()))
    source = find_child(inst, 'neutron_prod_info')
    assert get_attribute(source, 'NX_class') == 'NXsource'
    # `*_log`, not a bare NXlog: NXsource allows only one of those, so a second
    # per-pulse quantity could never join it.
    log = find_child(source, 'current_log')
    assert get_attribute(log, 'NX_class') == 'NXlog'
    assert stream_of(log)[0] == 'f144'
    assert value(source, 'depends_on') == '.'


def test_the_chopper_and_the_pulse_share_one_topic():
    """The layout check requires every log of one chopper to agree on a single topic,
    and a reference time on another topic could not be joined to them."""
    structure = to_nexus_structure(chopped(CHOPPER_ROOT), streams=REAL)
    inst = instrument_group(structure)
    disc = find_child(inst, 'psc1')
    pulse = find_child(find_child(inst, 'neutron_prod_info'), 'current_log')
    topics = {c['children'][0]['config']['topic']
              for c in disc['children'] if c.get('type') == 'group' and c['name'] != 'transformations'}
    assert len(topics) == 1
    assert pulse['children'][0]['config']['topic'] in topics
