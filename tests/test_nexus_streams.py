"""Monitor stream protocol is chosen by the instrument, never by a translator.

Some monitors belong on da00 histograms and some on ev44 events; the decision is a
property of the instrument setup. These tests pin the resolution order -- component
METADATA, then a niess stream selection recorded in provenance, then the component
type's established default -- and that no selection plus no default emits nothing.
"""
import pytest

from niess.nexus.nodes import find_child, get_attribute


def stream_module(group_node):
    """The filewriter module a stream group publishes through."""
    assert group_node is not None, 'expected a stream group'
    children = group_node['children']
    assert len(children) == 1
    return children[0]['module']


class FakeInstance:
    def __init__(self, metadata=None):
        self.metadata = metadata or []


class FakeMetaData:
    def __init__(self, name, value, mimetype='application/json'):
        self.name = name
        self.value = value
        self.mimetype = mimetype


class FakeProvenance:
    def __init__(self, extra):
        self.extra = extra


class FakeTranslation:
    def __init__(self, metadata=None, extra=None):
        self.instance = FakeInstance(metadata)
        self.provenance = FakeProvenance(extra) if extra is not None else None


EV44 = {'module': 'ev44', 'source': 'detector-0', 'topic': 'events'}
DA00 = {'module': 'da00', 'config': {'topic': 'histograms', 'source': 'monitor-0'}}


def test_no_selection_and_no_default_emits_nothing():
    from niess.nexus.streams import resolve_stream
    assert resolve_stream(FakeTranslation()) is None


def test_default_applies_when_instrument_is_silent():
    from niess.nexus.streams import resolve_stream
    assert stream_module(resolve_stream(FakeTranslation(), default=EV44)) == 'ev44'


def test_provenance_selection_overrides_default():
    from niess.nexus.streams import resolve_stream
    resolved = resolve_stream(FakeTranslation(extra={'nexus_stream': DA00}), default=EV44)
    assert stream_module(resolved) == 'da00'


def test_metadata_overrides_provenance_and_default():
    from json import dumps
    from niess.nexus.streams import resolve_stream

    metadata = [FakeMetaData('nexus_structure_stream_data',
                             dumps({'module': 'f144', 'config': {'topic': 'logs'}}))]
    resolved = resolve_stream(
        FakeTranslation(metadata=metadata, extra={'nexus_stream': DA00}), default=EV44
    )
    assert stream_module(resolved) == 'f144'


def test_ev44_and_da00_get_their_conventional_groups():
    from niess.nexus.streams import resolve_stream

    events = resolve_stream(FakeTranslation(), default=EV44)
    assert get_attribute(events, 'NX_class') == 'NXevent_data'

    histograms = resolve_stream(FakeTranslation(), default=DA00)
    assert get_attribute(histograms, 'NX_class') == 'NXdata'


# -- end to end, through a real instrument -----------------------------------

INSTR = """DEFINE INSTRUMENT stream_test(dummy=0)
TRACE
COMPONENT origin = Arm() AT (0, 0, 0) ABSOLUTE
COMPONENT sample = Arm() AT (0, 0, 5) RELATIVE origin
COMPONENT mon = TOF_monitor(xwidth=0.1, yheight=0.1, restore_neutron=1) AT (0, 0, 1) RELATIVE origin
END
"""


@pytest.fixture
def structure_with_metadata():
    from json import dumps
    from mccode_antlr.loader import parse_mcstas_instr
    from niess.nexus.via_instr import to_nexus_structure

    config = dumps({'module': 'da00', 'config': {'topic': 'mon_histograms', 'source': 'mon'}})
    src = INSTR.replace(
        'END',
        f'METADATA "application/json" "nexus_structure_stream_data" %{{{config}%}}\nEND',
    )
    return to_nexus_structure(parse_mcstas_instr(src), origin='sample')


def test_monitor_without_a_stream_gets_geometry_only():
    from mccode_antlr.loader import parse_mcstas_instr
    from niess.nexus.via_instr import to_nexus_structure

    structure = to_nexus_structure(parse_mcstas_instr(INSTR), origin='sample')
    monitor = find_child(structure['children'][0]['children'][0], 'mon')

    assert get_attribute(monitor, 'NX_class') == 'NXmonitor'
    assert find_child(monitor, 'OFF_GEOMETRY') is not None
    assert find_child(monitor, 'data') is None


def test_monitor_metadata_becomes_a_da00_stream(structure_with_metadata):
    monitor = find_child(structure_with_metadata['children'][0]['children'][0], 'mon')
    data = find_child(monitor, 'data')

    assert stream_module(data) == 'da00'
    assert data['children'][0]['config']['topic'] == 'mon_histograms'


def test_bifrost_detector_defaults_to_ev44():
    """The BIFROST tubes keep event streaming when the instrument says nothing."""
    from niess.nexus.via_instr.bifrost import (
        BIFROST_DETECTOR_TOPIC, BIFROST_REGISTRY, detector_tubes_translator,
    )
    from niess.nexus.streams import resolve_stream

    class DetectorTubes:
        type = type('T', (), {'name': 'Detector_tubes', 'category': None})()

        @staticmethod
        def collect_metadata():
            return []

    assert BIFROST_REGISTRY.resolve_builder(DetectorTubes()) is detector_tubes_translator

    default = {'module': 'ev44', 'source': 'arc=0;triplet=0', 'topic': BIFROST_DETECTOR_TOPIC}
    assert stream_module(resolve_stream(FakeTranslation(), default=default)) == 'ev44'


def test_ess_moderator_is_classified_without_instrument_specific_translators():
    """ESSource emits ESS_butterfly for every instrument, not only BIFROST.

    McCode files it under the 'mcstas-comps' category rather than 'sources', so the
    category fallback does not catch it and it needs an explicit entry in the generic
    table. Keeping that entry in niess.nexus.bifrost -- which an instrument now has to
    import deliberately -- silently downgraded every other ESS instrument's moderator
    to NXcoordinate_system.
    """
    from mccode_antlr.loader import parse_mcstas_instr
    from niess.nexus.via_instr import to_nexus_structure

    src = """DEFINE INSTRUMENT moderator_test(dummy=0)
TRACE
COMPONENT origin = Arm() AT (0, 0, 0) ABSOLUTE
COMPONENT source = ESS_butterfly(sector="W", beamline=2, Lmin=0.1, Lmax=10) AT (0, 0, 0) RELATIVE origin
COMPONENT sample = Arm() AT (0, 0, 10) RELATIVE origin
END
"""
    structure = to_nexus_structure(parse_mcstas_instr(src), origin='sample')
    moderator = find_child(structure['children'][0]['children'][0], 'source')
    assert get_attribute(moderator, 'NX_class') == 'NXmoderator'


def test_generic_niess_monitor_keeps_its_da00_stream():
    """A niess monitor converts fully without any instrument-specific registry.

    Every FrameMonitor subclass emits the McStas type `Frame_monitor` and attaches a
    da00 configuration as METADATA. While `Frame_monitor` was registered only on
    BIFROST_REGISTRY, a non-BIFROST instrument's monitors fell through to the generic
    fallback: NXcoordinate_system, with the stream config sitting unused on the
    instance.
    """
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from scipp import scalar, vector
    from scipp.spatial import rotations_from_rotvecs
    from niess.components import FissionChamber
    from niess.nexus.via_instr import to_nexus_structure

    assembler = Assembler('teaching', flavor=Flavor.MCSTAS)
    assembler.component('origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    FissionChamber.from_calibration({
        'name': 'mon',
        'position': vector([0, 0, 2.0], unit='m'),
        'orientation': rotations_from_rotvecs(vector([0, 0, 0.0], unit='deg')),
        'width': scalar(50.0, unit='mm'),
        'height': scalar(50.0, unit='mm'),
        'thickness': scalar(1.0, unit='mm'),
    }).to_mccode(assembler, at='origin', rotate='origin')
    assembler.component('sample_origin', 'Arm', at=((0, 0, 5), 'origin'))

    structure = to_nexus_structure(assembler.instrument, origin='sample_origin')
    monitor = find_child(structure['children'][0]['children'][0], 'mon')

    assert get_attribute(monitor, 'NX_class') == 'NXmonitor'
    assert find_child(monitor, 'OFF_GEOMETRY') is not None
    data = find_child(monitor, 'data')
    assert stream_module(data) == 'da00'
    assert data['children'][0]['config']['topic'] == 'teaching_beam_monitor'
