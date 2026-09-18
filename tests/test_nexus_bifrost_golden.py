"""BIFROST conversion parity against the pre-port moreniius baseline.

Both sides of this comparison are frozen on purpose, and it should stay that way. The
input is `bifrost.instr.json.gz`, a BIFROST instrument as it stood in August 2026 -- it
still names its choppers `...phase`, which 0.6.0 renamed to `delay` -- and the golden is
what `moreniius` produced for exactly that. Rebuilding the input from the live tree
would compare today's instrument against yesterday's output and prove nothing about the
port. What tracks the live tree is `tests/data/baseline/nexus.json.gz`.


``tests/data/bifrost_nexus_structure_golden.json`` is what ``moreniius`` produced for
``bifrost.instr.json`` before this port; ``bifrost_nexus_structure_golden.md`` explains
how it was captured and classifies every remaining difference.

These tests pin both halves of that claim: the structure matches, and the differences
that remain are exactly the four known categories. A new difference in any other place
fails here rather than slipping through.
"""
import gzip
import json
from pathlib import Path

import pytest

# Stored gzipped: together they are 6.5 MB of JSON that no one reads by hand, and
# the repository ignores bare *.json anyway
DATA = Path(__file__).parent / 'data'
GOLDEN = DATA / 'bifrost_nexus_structure_golden.json.gz'
INSTR = DATA / 'bifrost.instr.json.gz'

# Guide_gravity OFF_GEOMETRY groups and Slit NXpositioner groups that moreniius
# flattened to lists of child names; see the .md for the expr2nx root cause.
FLATTENED = ('OFF_GEOMETRY', 'xmin', 'xmax', 'ymin', 'ymax', 'xwidth', 'yheight')

# Values this port deliberately writes differently from the golden; each is
# justified in bifrost_nexus_structure_golden.md
CORRECTED = (
    'detector_number',
    'segment_rows',
    # The pixel pitch fix moves both the offsets and the one shared cylinder;
    # '/geometry.children/vertices' is the NXcylindrical_geometry, not OFF_GEOMETRY
    'y_pixel_offset',
    '/geometry.children/vertices',
    # NXdisk_chopper now carries 'delay' where the golden carried 'phase'; the frozen
    # instrument phases its choppers, so this one reads the comp default. See the .md
    'delay',
)


@pytest.fixture(scope='module')
def golden():
    return json.loads(gzip.decompress(GOLDEN.read_bytes()))


@pytest.fixture(scope='module')
def converted():
    from mccode_antlr.io.json import from_json
    from niess.nexus.via_instr import to_nexus_structure
    from niess.nexus.via_instr.bifrost import BIFROST_REGISTRY

    instr = from_json(gzip.decompress(INSTR.read_bytes()))
    return to_nexus_structure(instr, origin='sample_origin', registry=BIFROST_REGISTRY)


def instrument_children(structure):
    return structure['children'][0]['children'][0]['children']


def name_of(node):
    return node.get('name') or (node.get('config') or {}).get('name')


def nx_class(node):
    for attribute in (node.get('attributes') or []):
        if attribute['name'] == 'NX_class':
            return attribute['values']
    return None


def test_component_names_and_order_match(converted, golden):
    assert [name_of(c) for c in instrument_children(converted)] == \
           [name_of(c) for c in instrument_children(golden)]


def test_nx_class_census_matches(converted, golden):
    from collections import Counter

    def census(structure):
        return Counter(nx_class(c) or 'dataset' for c in instrument_children(structure))

    assert census(converted) == census(golden)


def test_flattened_groups_are_restored(converted, golden):
    """Where moreniius emitted a list of child names, we emit the real group.

    Only groups routed through ``make_nx`` were flattened: the 90 ``Guide_gravity``
    geometries and the 30 ``Slit`` positioners. The 29 elliptic guides and 5 frame
    monitors built their group directly and kept real geometry, so those must match
    the golden outright.
    """
    gold = {name_of(c): c for c in instrument_children(golden)}
    flattened_geometry, flattened_positioners, intact_geometry = 0, 0, 0

    for component in instrument_children(converted):
        for child in (component.get('children') or []):
            if name_of(child) not in FLATTENED:
                continue
            assert child['type'] == 'group', f'{name_of(component)}/{name_of(child)}'

            golden_child = next(
                c for c in (gold[name_of(component)].get('children') or [])
                if name_of(c) == name_of(child)
            )

            if golden_child.get('module') == 'dataset':
                # The golden lost the group: a string dataset of its child names
                assert golden_child['config']['type'] == 'string'
                names = [name_of(g) for g in child['children']]
                if name_of(child) == 'OFF_GEOMETRY':
                    assert names == golden_child['config']['values']
                    flattened_geometry += 1
                else:
                    # nexusformat also swallowed the positioner's own 'name' field,
                    # taking it for the group name, so only 'value' remained
                    assert names == ['name', 'value']
                    assert golden_child['config']['values'] == ['value']
                    flattened_positioners += 1
            else:
                assert golden_child['type'] == 'group'
                assert child == golden_child, f'{name_of(component)}/{name_of(child)}'
                intact_geometry += 1

    assert (flattened_geometry, flattened_positioners) == (90, 30)
    assert intact_geometry == 29 + 5  # elliptic guides, frame monitors


def test_detector_number_keeps_declared_int32(converted, golden):
    """moreniius widened the component's own .astype('int32') to int64."""
    gold = {name_of(c): c for c in instrument_children(golden)}
    triplets = 0

    for component in instrument_children(converted):
        if nx_class(component) != 'NXdetector':
            continue
        triplets += 1
        detector_number = next(c for c in component['children']
                               if name_of(c) == 'detector_number')
        golden_number = next(c for c in gold[name_of(component)]['children']
                             if name_of(c) == 'detector_number')
        assert detector_number['config']['type'] == 'int32'
        assert golden_number['config']['type'] == 'int64'
        assert detector_number['config']['values'] == golden_number['config']['values']

        # cylinders expresses no int32 intent upstream, so it stays as the golden has it
        geometry = next(c for c in component['children'] if name_of(c) == 'geometry')
        cylinders = next(c for c in geometry['children'] if name_of(c) == 'cylinders')
        assert cylinders['config']['type'] == 'int64'

    assert triplets == 45


def test_no_unclassified_differences(converted, golden):
    """Every leaf difference is one of the four categories in the .md."""
    differences = []

    def walk(a, b, path):
        if type(a) is not type(b):
            differences.append(path)
        elif isinstance(a, dict):
            for key in set(a) | set(b):
                if key not in a or key not in b:
                    differences.append(f'{path}.{key}')
                elif key == 'attributes':
                    walk(sorted(a[key], key=lambda x: x['name']),
                         sorted(b[key], key=lambda x: x['name']), f'{path}.{key}')
                else:
                    walk(a[key], b[key], f'{path}.{key}')
        elif isinstance(a, list):
            if len(a) != len(b):
                differences.append(f'{path}[len]')
            else:
                for i, (x, y) in enumerate(zip(a, b)):
                    walk(x, y, f'{path}/{name_of(x) if isinstance(x, dict) else i}')
        elif a != b:
            differences.append(path)

    walk(converted, golden, '')

    def classified(path):
        if any(f'/{name}.' in path or path.endswith(f'/{name}') for name in FLATTENED):
            return True
        if any(name in path for name in CORRECTED):
            return True
        return path.endswith('/mcstas.config.values')

    unclassified = [p for p in differences if not classified(p)]
    assert not unclassified, f'{len(unclassified)} unclassified: {unclassified[:10]}'
