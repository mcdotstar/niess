"""`Source` and `ESSource` became `Moderator` and `ESSModerator`; what was written before still reads.

Three things carry the old names: code importing them, JSON files tagged with them, and
the provenance block of every `.instr` niess emitted before the rename. The last is the
one that would fail silently -- a target that cannot match the recorded class falls back
to the component type, or to nothing -- so it is checked through dispatch rather than by
reading the field.
"""
import pytest


def test_the_old_names_still_import_and_say_so():
    import niess.components as components
    from niess.components import moderator

    with pytest.warns(DeprecationWarning, match='ESSModerator'):
        assert components.ESSource is moderator.ESSModerator
    with pytest.warns(DeprecationWarning, match='Moderator'):
        assert components.Source is moderator.Moderator

    with pytest.warns(DeprecationWarning, match='niess.components.moderator.ESSModerator'):
        from niess.components.source import ESSource
    assert ESSource is moderator.ESSModerator


def test_an_unknown_name_is_still_an_attribute_error():
    import niess.components as components
    with pytest.raises(AttributeError):
        components.NoSuchComponent


def test_an_ess_moderator_is_a_moderator():
    """Targets find where a flight path starts by this class."""
    from niess.components import ESSModerator, Moderator
    assert issubclass(ESSModerator, Moderator)


def test_a_json_file_tagged_essource_still_reads():
    from niess.components import ESSModerator
    from niess.io.json import from_json, to_json

    moderator = ESSModerator.from_calibration({'name': 'moderator'})
    written = to_json(moderator)
    assert written.startswith(b'{"name":"ESSModerator"'), 'written under the new name'

    old = written.replace(b'"name":"ESSModerator"', b'"name":"ESSource"', 1)
    assert from_json(old) == moderator


@pytest.mark.parametrize('recorded', [
    'niess.components.source.ESSource',
    'niess.components.moderator.ESSModerator',
])
def test_an_instr_written_before_the_rename_resolves_to_the_moderator(recorded):
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.components import ESSModerator
    from niess.dispatch import NiessRegistry
    from niess.provenance import NiessProvenance, add_niess_metadata

    assembler = Assembler('renamed', flavor=Flavor.MCSTAS)
    instance = assembler.component('moderator', 'ESS_butterfly', at=(0, 0, 0))
    add_niess_metadata(instance, source_type=recorded)

    provenance = NiessProvenance.from_instance(instance)
    assert provenance.source_type == 'niess.components.moderator.ESSModerator'

    registry = NiessRegistry()

    @registry.register(ESSModerator)
    def moderator(visit):
        return 'the moderator translator'

    assert registry.resolve_builder(instance) is moderator
