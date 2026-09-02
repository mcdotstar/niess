"""Which component feeds which, when the beam does not run in declaration order.

McCode has no way to say that a beam branches. Its instruments are a list, so the flow
through them is taken to be that list in order -- which is right until something splits
the beam. BIFROST does: after the sample one beam becomes many, and an instrument-reading
converter recorded every component past that point as fed by whichever happened to be
declared before it. That route had to be *handed* the real flow, as `graph=`.

A niess instrument states it. `__niess_flow__` is part of the tree, so the `@inputs` and
`@outputs` attributes follow from the instrument rather than from an argument.
"""
import pytest

from niess.instrument import Instrument, Mount
from niess.nexus import to_nexus_structure
from niess.nexus.nodes import children_of, get_attribute


@pytest.fixture(scope='module')
def instrument_group():
    from niess.bifrost import Primary, Tank
    from niess.bifrost.parameters import primary_parameters, tank_parameters
    from niess.nexus.bifrost import BIFROST_REGISTRY

    bifrost = Instrument(name='bifrost', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration(primary_parameters())),
        Mount(name='tank', content=Tank.from_calibration(tank_parameters()),
              relative_to='sample_origin'),
    ))
    structure = to_nexus_structure(bifrost, registry=BIFROST_REGISTRY)
    entry = structure['children'][0]
    return {node.get('name'): node for node in children_of(entry['children'][0])}


def test_a_component_records_what_feeds_it(instrument_group):
    sample = instrument_group['sample_origin']
    assert get_attribute(sample, 'inputs') == 'slit'
    assert get_attribute(sample, 'outputs') == 'slits'


def test_a_component_feeding_several_records_all_of_them(instrument_group):
    """The branch the declaration order cannot express: ten paths leave the slits."""
    outputs = get_attribute(instrument_group['slits'], 'outputs')
    assert isinstance(outputs, list)
    assert len(outputs) == 10
    assert 'elastic_monitor' in outputs
    assert sum(1 for name in outputs if 'radial_filter_collimator' in name) == 9


def test_one_name_is_written_as_a_name_not_a_list_of_one(instrument_group):
    """What the standard, and every reader of these files, expects."""
    assert isinstance(get_attribute(instrument_group['slits'], 'inputs'), str)


def test_a_composite_contributes_no_dangling_reference(instrument_group):
    """The graph is keyed on tree paths; the file is written in emitted names.

    A node that emits nothing -- a channel, an arm -- is in the graph and not in the
    file, so it must not appear in anything's inputs or outputs.
    """
    emitted = set(instrument_group)
    for node in instrument_group.values():
        for direction in ('inputs', 'outputs'):
            names = get_attribute(node, direction)
            if names is None:
                continue
            for name in ([names] if isinstance(names, str) else names):
                assert name in emitted, f'{name} is referenced but never written'
