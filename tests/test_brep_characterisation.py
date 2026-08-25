"""What the CAD export currently produces, so that changing how it is driven is safe.

`tests/test_brep.py` checks that four builders return a shape of roughly the right size.
That is not a net for moving the conversion onto the walk: it would keep passing while
every solid in the instrument moved, or while half of them stopped being emitted at all.

These pin the whole assembly -- how many solids, how much material, and where it is --
for the two instruments. Writing them turned up that the last of those is broken: every
solid is exported at the origin, because mccode_antlr's renderer computes each placement
inside a `try` whose `except Exception: pass` discards a TypeError raised for every
component. Four builder tests could not see it; each builds one shape and checks its
size. They are slow (about ten seconds for BIFROST's primary, which
is real OpenCascade work) and they are worth it exactly once, at the point where the
thing driving the conversion changes.

Numbers rather than a golden file: there are four of them per instrument, and a diff of
four numbers is readable where a diff of 188 breps is not.
"""
import pytest

importorskip = pytest.importorskip


@pytest.fixture(scope='module')
def assembly():
    importorskip('build123d', reason='niess.brep needs the brep extra')

    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.brep import instrument_to_assembly

    def build(*parts, name='instrument'):
        assembler = Assembler(name, flavor=Flavor.MCSTAS)
        for part in parts:
            part.to_mccode(assembler)
        return instrument_to_assembly(assembler.instrument)

    return build


def measure(compound) -> dict:
    """How many solids, how much material, and the extent of the whole thing."""
    solids = compound.solids()
    box = compound.bounding_box()
    return {
        'solids': len(solids),
        'volume': sum(solid.volume for solid in solids),
        'min': (box.min.X, box.min.Y, box.min.Z),
        'max': (box.max.X, box.max.Y, box.max.Z),
    }


def test_the_teaching_instrument_exports_what_it_did(assembly):
    from niess.teaching import Primary

    found = measure(assembly(Primary.from_calibration(), name='teaching'))
    assert found['solids'] == 7
    assert found['volume'] == pytest.approx(0.012216, rel=1e-4)


def test_the_bifrost_primary_exports_what_it_did(assembly):
    """188 solids from 158 components: a guide is a shell, not a block."""
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters

    found = measure(assembly(Primary.from_calibration(primary_parameters()),
                             name='bifrost'))
    assert found['solids'] == 188
    assert found['volume'] == pytest.approx(0.493135, rel=1e-4)


@pytest.mark.xfail(reason='every solid is exported at the origin; see the module note',
                   strict=True)
def test_the_instrument_is_as_long_as_the_instrument(assembly):
    """The beam runs 162 m from the moderator to the sample. The export spans 4.4 m.

    Nothing is placed. mccode_antlr's renderer computes each component's global
    placement inside a `try`, and `_eval_expr` raises `TypeError: float() argument must
    be a string or a real number, not 'Expr'` for every component in both instruments --
    which `except Exception: pass` then discards, leaving every shape at the origin.

    Marked strict, so this starts failing the moment the export is fixed, which is what
    should happen: driving the conversion from the tree gives it positions as scipp
    Variables and never calls `_eval_expr` at all.
    """
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters

    found = measure(assembly(Primary.from_calibration(primary_parameters()),
                             name='bifrost'))
    assert found['max'][2] - found['min'][2] == pytest.approx(162.0, rel=1e-2)


def test_nothing_is_placed_today(assembly):
    """The bug above, stated as what currently happens rather than what should.

    Recorded so that changing how the conversion is driven has something to change.
    """
    from niess.teaching import Primary

    found = measure(assembly(Primary.from_calibration(), name='teaching'))
    # the whole instrument is 10 m long; its export is 3 m, which is one guide
    assert found['max'][2] - found['min'][2] < 4.0


def test_every_registered_builder_is_reached(assembly):
    """A builder that stops being resolved would not change any number above.

    It would change these: the count of solids per niess class. That is what would
    actually break if dispatch moved and a class stopped matching.
    """
    import collections
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters
    from niess.brep.registry import DEFAULT_BREP_REGISTRY
    from niess.provenance import NiessProvenance

    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    Primary.from_calibration(primary_parameters()).to_mccode(assembler)

    resolved = collections.Counter()
    for instance in assembler.instrument.components:
        if DEFAULT_BREP_REGISTRY.resolve_builder(instance) is not None:
            provenance = NiessProvenance.from_instance(instance)
            resolved[provenance.source_type.rsplit('.', 1)[-1]] += 1

    assert dict(resolved) == {
        'ESSource': 1, 'EllipticGuide': 29, 'StraightGuide': 90,
        'Attenuator': 3, 'Jaw': 3, 'Slit': 2, 'Component': 1,
    }
    # 129 of 158. The rest -- 19 windows, 6 discs, 4 monitors -- resolve nothing,
    # because resolving against an emitted instance matches the niess class exactly
    # rather than walking up to a base. A Filter is a Component and there is a builder
    # registered for Component, but that is not how this lookup works; the object-side
    # one added for the walk does walk the MRO, so moving the conversion would give
    # those 29 the generic marker glyph. Worth deciding deliberately, not discovering.
    assert sum(resolved.values()) == 129
