"""A monitor's Kafka topic names the instrument, not the section it sits in.

``Section.to_mccode_nested`` places its components in a child assembler via
``Assembler.included()``, and a child's ``.name`` is the *section's* name. Deriving
the beam-monitor topic from ``assembler.name`` therefore published each section's
monitors to a different topic -- ``bifrost_curved_beam_monitor``,
``bifrost_expanding_beam_monitor``, and so on -- none of which anything subscribes to.
The topic must come from the root assembler, and must follow the instrument name so
different instruments get different topics.
"""
import json

import pytest
from mccode_antlr import Flavor
from mccode_antlr.assembler import Assembler

from niess.components.monitors import beam_monitor_topic
from niess.assembler import instrument_name, root_assembler


def stream_topics(instr):
    """Every da00 topic in an assembled instrument, by component name."""
    topics = {}
    for instance in instr.components:
        for metadata in instance.metadata:
            if metadata.name != 'nexus_structure_stream_data':
                continue
            config = json.loads(metadata.value)
            topics[instance.name] = config.get('topic') or config.get('config', {}).get('topic')
    return topics


def test_root_assembler_is_found_through_nesting():
    root = Assembler('bifrost', flavor=Flavor.MCSTAS)
    with root.included('bifrost_curved') as section:
        assert section.name == 'bifrost_curved'
        assert root_assembler(section) is root
        assert instrument_name(section) == 'bifrost'

        with section.included('bifrost_curved_inner') as deeper:
            assert instrument_name(deeper) == 'bifrost'

    assert instrument_name(root) == 'bifrost'


def test_beam_monitor_topic_is_derived_from_the_instrument():
    assert beam_monitor_topic('bifrost') == 'bifrost_beam_monitor'
    assert beam_monitor_topic('CSPEC') == 'cspec_beam_monitor'


@pytest.fixture(scope='module')
def primary():
    from niess.bifrost.parameters import primary_parameters
    from niess.bifrost import Primary
    return Primary.from_calibration(primary_parameters())


def assembled(primary, name):
    assembler = Assembler(name, flavor=Flavor.MCSTAS)
    primary.to_mccode(assembler)
    return assembler.instrument


def test_every_monitor_publishes_on_the_instrument_topic(primary):
    """Monitors live in several different nested sections; all share one topic."""
    topics = stream_topics(assembled(primary, 'bifrost'))

    assert len(topics) > 1, 'expected several monitors in the primary spectrometer'
    assert set(topics.values()) == {'bifrost_beam_monitor'}


def test_no_monitor_takes_its_section_name(primary):
    """The specific regression: section-derived topics like bifrost_curved_*."""
    topics = stream_topics(assembled(primary, 'bifrost'))
    section_named = {name: topic for name, topic in topics.items()
                     if topic != beam_monitor_topic('bifrost')}
    assert not section_named


def test_topic_follows_the_instrument_name(primary):
    """Renaming the instrument is how a different instrument gets its own topic."""
    topics = stream_topics(assembled(primary, 'CSPEC'))
    assert set(topics.values()) == {'cspec_beam_monitor'}


def test_topic_can_be_overridden_outright(primary):
    """An instrument that publishes somewhere else entirely can say so."""
    monitor = primary.curved.psc_monitor

    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    assembler.component('origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    monitor.to_mccode(assembler, at='origin', topic='ymir_detector')

    assert set(stream_topics(assembler.instrument).values()) == {'ymir_detector'}


def test_override_survives_nesting(primary):
    """The override is honoured from inside a section too."""
    monitor = primary.curved.psc_monitor

    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    assembler.component('origin', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    with assembler.included('bifrost_curved') as section:
        monitor.to_mccode(section, at='origin', topic='ymir_detector')

    assert set(stream_topics(assembler.instrument).values()) == {'ymir_detector'}
