"""Every instance a niess-built instrument produces carries provenance metadata.

Components built through ``Component.to_mccode`` are tagged for free, but a
composite that calls ``assembler.component()`` itself has to tag the result. When
one forgets, the instance is simply invisible to every post-hoc adapter -- no
error, no warning, just a component missing from the STEP assembly or the NeXus
file -- so assert the coverage rather than trusting each composite to remember.
"""
import pytest
from mccode_antlr import Flavor
from mccode_antlr.assembler import Assembler

from niess.provenance import NiessProvenance


@pytest.fixture(scope='module')
def bifrost():
    from niess.bifrost.parameters import primary_parameters, tank_parameters
    from niess.bifrost import Primary, Tank

    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    Primary.from_calibration(primary_parameters()).to_mccode(assembler)
    Tank.from_calibration(tank_parameters()).to_mccode(assembler, 'sample_origin')
    return assembler.instrument


def test_no_instance_is_left_untagged(bifrost):
    untagged = [c.name for c in bifrost.components
                if NiessProvenance.from_instance(c) is None]
    assert not untagged, f'{len(untagged)} untagged instances, e.g. {untagged[:5]}'


def test_composite_built_instances_are_tagged(bifrost):
    """The component types that only ever come from a hand-built composite."""
    by_type = {}
    for component in bifrost.components:
        provenance = NiessProvenance.from_instance(component)
        by_type.setdefault(component.type.name, []).append(provenance)

    for type_name in ('Monochromator_Rowland', 'Detector_tubes', 'Radial_col_filter'):
        assert type_name in by_type, f'{type_name} missing from the assembled instrument'
        assert all(p is not None for p in by_type[type_name])


def test_reference_frames_are_distinguishable_from_components(bifrost):
    """Coordinate-reference Arms take a role that sets them apart."""
    roles = {}
    for component in bifrost.components:
        provenance = NiessProvenance.from_instance(component)
        roles.setdefault(provenance.role, 0)
        roles[provenance.role] += 1

    assert roles.keys() == {'physical-component', 'reference-frame'}
    assert roles['reference-frame'] > 0
    assert roles['physical-component'] > 0


# -- the name comes off the instance ------------------------------------------

def test_the_name_is_read_off_the_instance_not_the_payload(bifrost):
    """Schema 3 stopped writing `source_name`, because it could only ever repeat.

    Every writer passed the same string it had just handed `assembler.component`, and
    `Instance` keeps that name verbatim -- `add_component` raises on a collision rather
    than renaming around it. So the field was a second copy of `instance.name` on a
    block already attached to that instance, and two copies of one name is a thing that
    can disagree.
    """
    for component in bifrost.components:
        provenance = NiessProvenance.from_instance(component)
        assert provenance.schema_version == 3
        assert provenance.source_name == component.name


def test_a_file_that_still_carries_the_name_is_taken_at_its_word():
    """Schema 1 and 2 wrote it, and those files still have to read back."""
    from json import dumps
    from mccode_antlr.common import MetaData
    from niess.provenance import (NIESS_PROVENANCE_METADATA_MIMETYPE,
                                  NIESS_PROVENANCE_METADATA_NAME,
                                  NIESS_PROVENANCE_METADATA_NAMESPACE)

    assembler = Assembler('old', flavor=Flavor.MCSTAS)
    instance = assembler.component('emitted_name', 'Arm', at=((0, 0, 0), 'ABSOLUTE'))
    instance.add_metadata(MetaData.from_instance_tokens(
        instance.name,
        NIESS_PROVENANCE_METADATA_MIMETYPE,
        NIESS_PROVENANCE_METADATA_NAME,
        dumps({'namespace': NIESS_PROVENANCE_METADATA_NAMESPACE,
               'schema_version': 2,
               'source_type': 'niess.components.component.Component',
               'source_name': 'what_schema_2_wrote',
               'role': 'physical-component',
               'extra': {}}),
    ))

    provenance = NiessProvenance.from_instance(instance)
    assert provenance.schema_version == 2
    assert provenance.source_name == 'what_schema_2_wrote'
