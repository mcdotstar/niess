"""BIFROST's streams, as ECDC binds them for the real instrument.

`niess/bifrost/ecdc/bindings.yaml` is a verbatim copy of ECDC's. These tests are what
makes refreshing it safe: every binding must either be written by niess or be excused
in `NOT_SIMULATED` with a reason, so a binding ECDC adds or renames fails here rather
than silently going missing from the file.

Two files come from one set of bindings. A *real* one names every bound stream exactly
as bound. A *simulated* one names only what the simulation publishes, with every EPICS
source prefixed so that it can never be mistaken for the real PV.
"""
import pytest

from niess.nexus import BoundStreams, UnitMismatch, to_nexus_structure
from niess.nexus.bindings import SIMULATION_PREFIX, parse_bindings
from niess.nexus.nodes import children_of, get_attribute


@pytest.fixture(scope='module')
def bindings():
    from niess.bifrost.ecdc import bindings
    return bindings()


@pytest.fixture(scope='module')
def instrument():
    from niess.bifrost.bifrost import instrument
    return instrument()


def _structure(instrument, streams):
    from niess.nexus.bifrost import BIFROST_REGISTRY
    return to_nexus_structure(instrument, registry=BIFROST_REGISTRY, streams=streams)


@pytest.fixture(scope='module')
def real(instrument):
    from niess.bifrost.ecdc import bifrost_streams
    # not strict: the mask is simulated and has no binding, which is the point of it
    return _structure(instrument, bifrost_streams(simulated=False, strict=False))


@pytest.fixture(scope='module')
def simulated(instrument):
    from niess.bifrost.ecdc import bifrost_streams
    return _structure(instrument, bifrost_streams())


def streams_by_key(structure) -> dict[str, dict]:
    """Every stream module, keyed as a bindings file keys it.

    A binding's key is the log's path below `NXinstrument`, dot-separated -- the group
    that holds the stream module, not the module itself.
    """
    found = {}

    def walk(node, path):
        for child in children_of(node):
            if child.get('type') == 'group':
                walk(child, path + [child['name']])
            elif child.get('module') in ('f144', 'tdct', 'ev44', 'da00'):
                found['.'.join(path)] = {'node': node, 'module': child['module'],
                                         **child['config']}

    instrument_group = structure['children'][0]['children'][0]
    walk(instrument_group, [])
    return found


# -- the vendored file ------------------------------------------------------------

def test_the_vendored_file_is_readable_and_complete(bindings):
    assert len(bindings) == 217
    for binding in bindings.values():
        assert binding.schema in ('f144', 'tdct', 'ev44', 'da00'), binding.key
        assert binding.source_type in ('forwarder', 'efu'), binding.key


def from_binding(stream, binding, prefix: str = '') -> bool:
    """Whether a written stream is the one a binding describes."""
    source = (prefix + binding.source if binding.source_type == 'forwarder'
              else binding.source)
    same = (stream['module'] == binding.schema and stream['source'] == source
            and stream['topic'] == binding.topic)
    if same and binding.schema == 'f144':
        same = (stream['dtype'] == binding.dtype
                and stream['value_units'] == binding.value_units)
    return same


def test_every_binding_is_written_or_excused(bindings, real):
    """The coverage gate. A refresh that adds or changes a binding lands here first.

    A real file names every bound stream exactly as bound, unless `NOT_SIMULATED`
    says why not.
    """
    from niess.bifrost.ecdc import not_simulated
    written = streams_by_key(real)
    unexplained = [key for key, binding in bindings.items()
                   if not_simulated(key) is None
                   and not (key in written and from_binding(written[key], binding))]
    assert unexplained == []


def test_nothing_excused_is_written_anyway(bindings, real):
    """An excuse that no longer applies should be removed, not left to rot."""
    from niess.bifrost.ecdc import not_simulated
    written = streams_by_key(real)
    stale = [key for key, binding in bindings.items()
             if not_simulated(key) and key in written
             and from_binding(written[key], binding)]
    assert stale == []


# -- the simulated file -------------------------------------------------------------

def test_a_simulated_epics_source_is_never_the_real_one(bindings, simulated):
    """The file names the real instrument's topics, but not its PVs.

    A simulated producer that reached the real network would then publish under names
    nothing real uses, rather than impersonating a real motor or chopper.
    """
    from niess.bifrost.ecdc import not_simulated
    written = streams_by_key(simulated)
    for key, binding in bindings.items():
        if key in written and not_simulated(key) is None:
            assert from_binding(written[key], binding, SIMULATION_PREFIX), key


def test_every_simulated_epics_source_is_prefixed(simulated):
    """Bound or not: the mask's edges have no binding and are prefixed all the same."""
    for key, stream in streams_by_key(simulated).items():
        if stream['module'] in ('f144', 'tdct'):
            assert stream['source'].startswith(SIMULATION_PREFIX), key


def test_a_simulation_writes_only_what_it_has(simulated):
    """No setpoint and no done flag: a simulation has neither, and leaving them out is
    part of what says the file is simulated. It has the controller's three delays,
    because they are its knobs, and their total."""
    written = streams_by_key(simulated)
    absent = ('target_value', 'idle_flag', 'rotation_speed_setpoint')
    assert [key for key in written if key.rpartition('.')[2] in absent] == []
    chopper = sorted(key.rpartition('.')[2] for key in written
                     if key.startswith('pulse_shaping_chopper_1.'))
    assert chopper == ['delay', 'experiment_delay', 'mechanical_delay', 'park_angle',
                       'pulse_delay', 'rotation_speed', 'top_dead_center']


def test_chopper_speeds_are_the_nexus_signed_pvs(real, simulated):
    """ESS's Spd_R/Spd_S are positive clockwise facing away from the source, NeXus's
    rotation_speed anticlockwise. ECDC's file binds the former; niess corrects it to
    the SpdNexus-* PVs the controllers serve for NeXus, in both kinds of file."""
    real, simulated = streams_by_key(real), streams_by_key(simulated)
    for disc in ('pulse_shaping_chopper_1', 'bandwidth_chopper_2'):
        root = real[f'{disc}.delay']['source'].removesuffix(':TotDly')
        assert real[f'{disc}.rotation_speed']['source'] == f'{root}:SpdNexus-R'
        assert (real[f'{disc}.rotation_speed_setpoint']['source']
                == f'{root}:SpdNexus-RB')
        assert (simulated[f'{disc}.rotation_speed']['source']
                == f'{SIMULATION_PREFIX}{root}:SpdNexus-R')


def test_the_bound_axes_are_the_ones_ecdc_names(simulated):
    written = streams_by_key(simulated)
    for key in ('divergence_slit_1.left.value', 'divergence_slit_3.right.value',
                'sample_jaws.top.value', 'sample_rotation.value',
                'detector_tank_angle.value', 'source.pulse_charge',
                'channel_9_5_triplet.data'):
        assert key in written, key


def test_the_sample_hangs_from_the_goniometers_as_ecdc_chains_them(real):
    """sample -> goniometer_upper (x) -> goniometer_lower (z) -> sample_rotation (y)."""
    from niess.nexus.nodes import find_child
    instrument = real['children'][0]['children'][0]
    chain = []
    path = find_child(find_child(instrument, 'sample'), 'depends_on')['config']['values']
    while '/sample_origin/' not in path:
        positioner, _ = path.removeprefix('/entry/instrument/').split('/')
        value = find_child(find_child(instrument, positioner), 'value')
        chain.append((positioner, get_attribute(value, 'vector')))
        path = get_attribute(value, 'depends_on')
    assert chain == [('goniometer_upper', [1.0, 0.0, 0.0]),
                     ('goniometer_lower', [0.0, 0.0, 1.0]),
                     ('sample_rotation', [0.0, 1.0, 0.0])]


def test_divergence_slits_are_numbered_along_the_beam(instrument):
    """ECDC's slit 1 is the one furthest from the sample."""
    from niess.walk import visits
    from scipp import norm
    distance = {v.name: float(norm(v.obj.position).to(unit='m').value)
                for v in visits(instrument) if v.name.startswith('divergence_slit_')}
    assert sorted(distance, key=distance.get) == [
        'divergence_slit_1', 'divergence_slit_2', 'divergence_slit_3']


@pytest.fixture(scope='module')
def emitted(instrument):
    from niess.mccode import to_mccode
    return to_mccode(instrument, insert_provenance_metadata=False)


def test_each_simulated_log_names_a_parameter_in_the_published_unit(simulated, emitted):
    """The number a run sets is the number the file records, with no conversion between.

    Every log a simulation publishes from a knob says which knob, and the instrument
    declares that knob in the unit the log is published in -- millimetres for a jaw,
    nanoseconds for a chopper delay. Whatever McStas wants instead is converted where
    the knob is inserted into a component.
    """
    from niess.components.motor import unquote
    declared = {p.name: unquote(p.unit) for p in emitted.parameters}
    checked = 0
    for key, stream in streams_by_key(simulated).items():
        parameter = get_attribute(stream['node'], 'simulation_parameter')
        if parameter is None:
            continue
        assert parameter in declared, key
        assert declared[parameter] == stream['value_units'], key
        checked += 1
    # 6 discs x 5 knobs (speed, park, and three delays; pulse_delay is shared but each
    # disc logs it), 2 x 3 divergence edges, 4 mask and 4 jaw edges, 4 angles (sample
    # rotation, two goniometer tilts, detector tank)
    assert checked == 30 + 6 + 8 + 4


def test_the_tdc_and_pulse_are_published_by_the_clock_not_a_parameter(simulated):
    written = streams_by_key(simulated)
    for key in ('pulse_shaping_chopper_1.top_dead_center',
                'pulse_shaping_chopper_1.delay', 'source.pulse_charge'):
        assert get_attribute(written[key]['node'], 'simulation_parameter') is None, key


# -- the binder on its own -----------------------------------------------------------

def test_a_knob_in_the_wrong_unit_is_refused():
    """A conversion hidden between the knob and the stream is the thing to avoid."""
    from niess.components.motor import Motor
    bindings = parse_bindings({'slit.left.value': {
        'schema': 'f144', 'source': 'X:Mtr.RBV', 'topic': 'motion',
        'dtype': 'double', 'value_units': 'mm', 'source_type': 'forwarder'}})

    class Slit:
        name = 'slit'

    knob = Motor(name='slit_left', unit='m', source='slit_left', topic='t', default=0.0)
    with pytest.raises(UnitMismatch, match="'slit_left' is declared in 'm'"):
        BoundStreams(bindings).bind(Slit(), 'left', knob)


def test_an_efu_source_is_never_prefixed():
    """The event formation unit chooses it, so the simulation must use it as it is."""
    bindings = parse_bindings({'det.data': {
        'schema': 'ev44', 'source': 'arc=0;triplet=0', 'topic': 'detector',
        'source_type': 'efu'}})
    assert BoundStreams(bindings).stream('det')['source'] == 'arc=0;triplet=0'
