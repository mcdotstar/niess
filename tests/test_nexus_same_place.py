"""A child that sits exactly where its component sits.

NeXus lets a `depends_on` name one thing: the last transformation in a chain, or `"."`.
Not a group -- an `NXtransformations` group carries no `transformation_type`, `vector` or
offset, so a reader arriving at one has nothing to apply and nowhere to continue.

A jaw's edge motors are at the jaw. Saying so means naming the jaw's own chain end, and a
translator cannot: it builds its children before the component is placed, and the chain
end is not even predictable from the component -- a jaw sitting at its frame's origin
emits no transformations at all, so its chain end is a path in some *other* group. So a
child writes `SAME_PLACE` and `_placed` resolves it once the placement is known.
"""
import pytest
from scipp import scalar, vector
from scipp.spatial import rotations_from_rotvecs

from niess.instrument import Instrument, Mount
from niess.nexus import to_nexus_structure
from niess.nexus.nodes import SAME_PLACE, attribute, dataset, find_child, group, \
    resolve_same_place


def value(node, name):
    return find_child(node, name)['config']['values']


# -- the rewrite itself --------------------------------------------------------

def test_it_rewrites_a_dataset_an_attribute_and_a_nested_child():
    """A `depends_on` is a dataset on a component and an attribute on a transformation."""
    node = group('jaw', nx_class='NXaperture', children=[
        dataset('depends_on', SAME_PLACE),
        group('left', nx_class='NXpositioner',
              children=[dataset('depends_on', SAME_PLACE)]),
    ])
    node['attributes'].append(attribute('depends_on', SAME_PLACE))

    resolve_same_place(node, '/entry/instrument/jaw/transformations/rotation_y')

    resolved = '/entry/instrument/jaw/transformations/rotation_y'
    assert value(node, 'depends_on') == resolved
    assert value(find_child(node, 'left'), 'depends_on') == resolved
    assert [a for a in node['attributes'] if a['name'] == 'depends_on'][0]['values'] \
        == resolved


def test_it_leaves_a_real_path_alone():
    node = group('jaw', nx_class='NXaperture',
                 children=[dataset('depends_on', '/entry/instrument/frame/t')])
    resolve_same_place(node, '/somewhere/else')
    assert value(node, 'depends_on') == '/entry/instrument/frame/t'


# -- and what it is for --------------------------------------------------------

def _jaw_instrument(position):
    """One jaw, at ``position`` in the instrument's frame."""
    from niess.components import Section
    from niess.components.aperture import Jaw

    jaw = Jaw.from_calibration({
        'name': 'jaw', 'position': position,
        'orientation': rotations_from_rotvecs(vector([0, 0, 0.0], unit='deg')),
        'width': scalar(0.03, unit='m'), 'height': scalar(0.05, unit='m'),
    })

    class Jawed(Section):
        jaw: Jaw
        _flat: bool = True

    return Instrument(name='jawed', parts=(Mount(name='m', content=Jawed(jaw=jaw)),))


def _emitted_jaw(position):
    structure = to_nexus_structure(_jaw_instrument(position))
    return find_child(structure['children'][0]['children'][0], 'jaw')


@pytest.mark.parametrize('position', [
    vector([0, 0, 5.0], unit='m'),      # placed: the chain ends inside the jaw
    vector([0, 0, 0.0], unit='m'),      # at its frame's origin: no transformations at all
], ids=['placed', 'at-the-origin'])
def test_a_motor_hangs_where_its_aperture_hangs(position):
    """The edges are driven within the opening, not moved relative to it."""
    jaw = _emitted_jaw(position)
    own = value(jaw, 'depends_on')
    for edge in ('left', 'right'):
        assert value(find_child(jaw, edge), 'depends_on') == own


def test_at_the_origin_the_chain_end_is_not_in_the_jaw_at_all():
    """The case a hand-written path gets wrong.

    With nothing to place it, the jaw emits no `NXtransformations` group, so its chain
    end belongs to whatever it hangs from. A translator spelling out
    `.../jaw/transformations/rotation_y` would name a node that was never written.
    """
    jaw = _emitted_jaw(vector([0, 0, 0.0], unit='m'))
    assert find_child(jaw, 'transformations') is None
    assert 'jaw/transformations' not in value(jaw, 'depends_on')


def test_no_sentinel_survives_into_a_file():
    """A leak would be a path no reader can resolve, so it must not be possible."""
    from json import dumps
    written = dumps(to_nexus_structure(_jaw_instrument(vector([0, 0, 5.0], unit='m'))))
    assert SAME_PLACE not in written
    assert '\\u0000' not in written


# -- the name a chain link is written under ------------------------------------

def test_a_renamed_component_chains_off_the_name_it_was_written_under():
    """A translator may emit under a name that is not the visit's, and BIFROST's do.

    One visit to `channel_1_1` emits `channel_1_1_monochromator` and
    `channel_1_1_triplet`. Naming the chain links from the visit pointed every one of
    them at `/entry/instrument/channel_1_1/...`, a group nobody ever writes -- 90
    dangling `depends_on` references in a BIFROST file, invisible because the structure
    the tests validate is built without the registry that emits them.
    """
    from niess.components import Section
    from niess.components.component import Component
    from niess.nexus import NEXUS_REGISTRY, component_body, emit
    from niess.nexus.registry import NiessNexusRegistry

    registry = NiessNexusRegistry(parent=NEXUS_REGISTRY)

    class Renaming:
        @staticmethod
        def leaf(visit):
            emit(visit, component_body('NXaperture', name=f'{visit.name}_renamed',
                                       position=vector([0, 0, 3.0], unit='m')))

    class Thing(Component):
        pass

    registry.register(Thing)(Renaming)

    thing = Thing(name='original', position=vector([0, 0, 1.0], unit='m'),
                  orientation=rotations_from_rotvecs(vector([0, 0, 0.0], unit='deg')))

    class Held(Section):
        thing: Thing
        _flat: bool = True

    instrument = Instrument(name='renaming',
                            parts=(Mount(name='m', content=Held(thing=thing)),))
    group = to_nexus_structure(instrument, registry=registry)['children'][0]['children'][0]

    emitted = find_child(group, 'original_renamed')
    assert emitted is not None, 'the translator renames what it emits'
    assert find_child(group, 'original') is None
    # the chain link names the group that exists, not the visit that made it
    assert value(emitted, 'depends_on').startswith('/entry/instrument/original_renamed/')
