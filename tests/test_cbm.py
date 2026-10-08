"""BIFROST's beam monitors as the cbm Event Formation Unit reads them.

Three things must agree about every monitor: the EFU's configuration, the collector
that records the monitor's rays for replay to that EFU, and the NeXus file that stores
what the EFU publishes. All three are built from the monitor's `CbmChannel`.
"""
import pytest

from niess.cbm import CbmChannel, Collect, efu_config, monitor_channels

#: cbm1-cbm3 exactly as ECDC's BIFROST cbm EFU configuration has them. The real cbm4
#: and cbm5 publish events; simulated, every monitor is histogrammed.
ECDC_TOPOLOGY = [
    {"FEN": 0, "Channel": 0, "Type": "EVENT_0D", "Source": "cbm1", "Schema": "da00",
     "MaxTofBin": 71428571, "BinCount": 744, "AggregatedFrames": 14},
    {"FEN": 1, "Channel": 0, "Type": "IBM", "Source": "cbm2", "Schema": "da00",
     "MaxTofBin": 71428571, "BinCount": 744, "AggregatedFrames": 14},
    {"FEN": 2, "Channel": 0, "Type": "IBM", "Source": "cbm3", "Schema": "da00",
     "MaxTofBin": 71428571, "BinCount": 744, "AggregatedFrames": 14},
]

MONITORS = ('psc_monitor', 'overlap_monitor', 'bandwidth_monitor',
            'normalization_monitor', 'elastic_monitor')


@pytest.fixture(scope='module')
def instrument():
    from niess.bifrost.bifrost import instrument
    return instrument()


def test_every_bifrost_monitor_has_a_channel(instrument):
    assert [name for name, _ in monitor_channels(instrument)] == list(MONITORS)


def test_efu_config_is_ecdcs(instrument):
    config = efu_config(instrument)
    assert {k: config[k] for k in ('Detector', 'TypeSubType', 'MaxPulseTimeDiffNS',
                                   'MaxTOFNS', 'MonitorRing', 'MaxFENId')} == {
        'Detector': 'CBM', 'TypeSubType': 16, 'MaxPulseTimeDiffNS': 71428600,
        'MaxTOFNS': 142857142, 'MonitorRing': 11, 'MaxFENId': 4}
    assert config['Topology'][:3] == ECDC_TOPOLOGY
    for entry, source in zip(config['Topology'][3:], ('cbm4', 'cbm5')):
        assert entry == ECDC_TOPOLOGY[0] | {'FEN': int(source[-1]) - 1, 'Source': source}


def test_the_efu_can_not_histogram_positions():
    with pytest.raises(ValueError, match='EVENT_2D'):
        CbmChannel(fen=3, source='cbm4', type='EVENT_2D', width=32, height=32)
    channel = CbmChannel(fen=3, source='cbm4', type='EVENT_2D', schema='ev44',
                         width=32, height=32)
    assert channel.topology() == {'FEN': 3, 'Channel': 0, 'Type': 'EVENT_2D',
                                  'Source': 'cbm4', 'Schema': 'ev44',
                                  'PixelOffset': 1, 'Width': 32, 'Height': 32}


def test_a_shared_fen_is_refused(instrument):
    from msgspec.structs import replace
    primary = instrument.mount_of('primary').content
    clash = replace(primary.normalization_monitor,
                    readout=replace(primary.normalization_monitor.readout, fen=0))
    parts = tuple(
        replace(m, content=replace(primary, normalization_monitor=clash))
        if m.name == 'primary' else m for m in instrument.parts)
    with pytest.raises(ValueError, match='both claim FEN 0'):
        efu_config(replace(instrument, parts=parts))


def test_a_calibration_may_give_the_channel_as_fields():
    from niess.cbm import as_channel
    assert as_channel({'fen': 2, 'source': 'cbm3', 'type': 'IBM'}) == CbmChannel(
        fen=2, source='cbm3', type='IBM')


# -- McStas ------------------------------------------------------------------------

STUB = """DEFINE COMPONENT {name}
SETTING PARAMETERS (string ring=0, int fen_value=0, int channel_value=0,
                    keep_probability=1, efficiency=1, string filename=0{extra})
TRACE
%{{
%}}
END
"""


@pytest.fixture(scope='module')
def collectors(tmp_path_factory):
    """Stand-ins for mcstas-readout-master's collectors: only their parameters matter."""
    root = tmp_path_factory.mktemp('collectors')
    (root / 'CollectorBM0.comp').write_text(STUB.format(name='CollectorBM0', extra=''))
    (root / 'CollectorBMI.comp').write_text(
        STUB.format(name='CollectorBMI', extra=', int adc_value=0, int sum_value=0'))
    return str(root)


def _emit(instrument, collect=None):
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.mccode import to_mccode
    return to_mccode(instrument, assembler=Assembler(instrument.name, flavor=Flavor.MCSTAS),
                     collect=collect)


@pytest.fixture(scope='module')
def collecting(instrument, collectors):
    return _emit(instrument, Collect(filename='monitors', registry=collectors,
                                     keep_probability={'psc_monitor': 0.25}))


def test_without_collect_there_are_no_collectors(instrument):
    instr = _emit(instrument)
    assert not [c for c in instr.components if c.type.name.startswith('Collector')]
    assert 'cbm_hit' not in ' '.join(x.source for x in instr.user)


def test_each_monitor_is_followed_by_its_collector(collecting):
    names = [c.name for c in collecting.components]
    for name in MONITORS:
        follower = collecting.components[names.index(name) + 1]
        assert follower.name == f'{name}_collector'
        assert str(follower.when) == 'cbm_hit'
        assert follower.group is None
        assert [x.source for x in follower.extend] == ['cbm_hit = 0;']
        monitor = collecting.components[names.index(name)]
        assert monitor.extend[-1].source == (
            'if (SCATTERED) { cbm_hit = 1; cbm_fibre = 22; }')


def test_collector_types_and_parameters(collecting):
    def collector(name):
        return next(c for c in collecting.components if c.name == f'{name}_collector')

    def value(instance, parameter):
        return str(next(p.value for p in instance.parameters if p.name == parameter))

    kinds = {name: collector(name).type.name for name in MONITORS}
    assert kinds == {'psc_monitor': 'CollectorBM0', 'overlap_monitor': 'CollectorBMI',
                     'bandwidth_monitor': 'CollectorBMI',
                     'normalization_monitor': 'CollectorBM0',
                     'elastic_monitor': 'CollectorBM0'}
    for fen, name in enumerate(MONITORS):
        assert value(collector(name), 'fen_value') == str(fen)
        assert value(collector(name), 'ring') == '"cbm_fibre"'
        assert value(collector(name), 'filename') == '"monitors"'
    assert float(value(collector('psc_monitor'), 'keep_probability')) == 0.25
    assert float(value(collector('elastic_monitor'), 'keep_probability')) == 1.0
    assert value(collector('overlap_monitor'), 'adc_value') == '1'
    efficiencies = {name: float(value(collector(name), 'efficiency')) for name in MONITORS}
    assert efficiencies == {'psc_monitor': 1e-7, 'overlap_monitor': 1e-5,
                            'bandwidth_monitor': 1e-5, 'normalization_monitor': 1e-5,
                            'elastic_monitor': 0.23}


def test_a_monitor_efficiency_scales_its_collector(collectors):
    """Given in the monitor's calibration, as the rest of what describes it is."""
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters
    from niess.instrument import Instrument, Mount
    parameters = primary_parameters()
    parameters['normalization_monitor']['efficiency'] = 1e-4
    primary = Primary.from_calibration(parameters)
    instr = _emit(Instrument(name='bifrost', parts=(Mount(name='primary', content=primary),)),
                  Collect(registry=collectors))
    recorder = next(c for c in instr.components if c.name == 'normalization_monitor_collector')
    efficiency = next(p.value for p in recorder.parameters if p.name == 'efficiency')
    assert float(str(efficiency)) == 1e-4


@pytest.mark.parametrize('keep, efficiency', [(0, 1), (1.5, 1), (1, -0.1), (1, 2)])
def test_impossible_thinning_or_efficiency_is_refused(keep, efficiency):
    from niess.cbm import collector
    channel = CbmChannel(fen=0, source='cbm1')
    with pytest.raises(ValueError, match='psc_monitor'):
        collector(channel, Collect(keep_probability=keep), 'psc_monitor', efficiency)


def test_the_elastic_monitor_keeps_its_group_and_cassette(collecting):
    monitor = next(c for c in collecting.components if c.name == 'elastic_monitor')
    assert monitor.group == 'filters_monitor'
    assert monitor.extend[0].source == 'if (SCATTERED) secondary_cassette = 10;'


def test_the_particle_variables_are_declared_once(collecting):
    declared = [x.source for x in collecting.user]
    assert declared.count('int cbm_hit;') == 1
    assert declared.count('int cbm_fibre;') == 1


# -- NeXus -------------------------------------------------------------------------

def _monitor_streams(instrument, efu_monitors):
    from niess.bifrost.ecdc import bifrost_streams
    from niess.nexus import to_nexus_structure
    from niess.nexus.bifrost import BIFROST_REGISTRY
    from .test_bifrost_ecdc_bindings import streams_by_key
    structure = to_nexus_structure(instrument, registry=BIFROST_REGISTRY,
                                   streams=bifrost_streams(), efu_monitors=efu_monitors)
    found = streams_by_key(structure)
    return {name: found[f'{name}.data'] for name in MONITORS}


def test_efu_monitors_publish_what_the_efu_does(instrument):
    from niess.bifrost.ecdc import bindings
    streams = _monitor_streams(instrument, efu_monitors=True)
    for fen, name in enumerate(MONITORS):
        assert streams[name]['module'] == 'da00'
        assert streams[name]['source'] == f'cbm{fen + 1}'
        assert streams[name]['topic'] == 'bifrost_beam_monitor'
    # where ECDC histograms a monitor, the file says exactly what ECDC's does
    for name in MONITORS[:3]:
        bound = bindings()[f'{name}.data']
        for key in ('variables', 'constants', 'attributes'):
            assert streams[name][key] == bound.extra[key]


def test_otherwise_monitors_publish_mcstas_histograms(instrument):
    streams = _monitor_streams(instrument, efu_monitors=False)
    assert {s['source'] for s in streams.values()} == set(MONITORS)
