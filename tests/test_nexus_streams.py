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












