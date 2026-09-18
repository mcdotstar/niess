from pytest import approx, importorskip


def _origin():
    import scipp as sc
    return sc.vector([0.0, 0.0, 0.0], unit='m')


def _identity():
    import scipp as sc
    return sc.spatial.rotation(value=[0.0, 0.0, 0.0, 1.0])


def _assembly_child(assembly):
    solids = assembly.solids()
    assert len(solids) == 1
    return solids[0]


def test_to_mccode_adds_niess_metadata():
    import scipp as sc
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.components import StraightGuide
    from niess.provenance import read_niess_metadata

    guide = StraightGuide(
        name='g1',
        position=_origin(),
        orientation=_identity(),
        length=sc.scalar(3.0, unit='m'),
        left=1.0,
        right=1.0,
        top=1.0,
        bottom=1.0,
        width=sc.scalar(0.1, unit='m'),
        height=sc.scalar(0.2, unit='m'),
    )

    assembler = Assembler('guide_test', flavor=Flavor.MCSTAS)
    instance = guide.to_mccode(assembler, insert_provenance_metadata=True)
    payload = read_niess_metadata(instance)

    assert payload is not None
    assert payload['source_name'] == 'g1'
    assert payload['source_type'].endswith('StraightGuide')
    assert payload['role'] == 'physical-component'


def test_a_guide_is_drawn_around_its_own_substrate():
    importorskip('build123d')
    import scipp as sc
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.brep import to_assembly
    from niess.instrument import Instrument, Mount
    from niess.components import StraightGuide
    from niess.provenance import add_niess_metadata

    width, height, substrate = 0.1, 0.2, 0.02

    guide = StraightGuide(
        name='g1',
        position=_origin(),
        orientation=_identity(),
        length=sc.scalar(3.0, unit='m'),
        left=1.0,
        right=1.0,
        top=1.0,
        bottom=1.0,
        width=sc.scalar(width, unit='m'),
        height=sc.scalar(height, unit='m'),
        substrate=sc.scalar(substrate, unit='m'),
    )

    assembly = to_assembly(Instrument(
        name='guide_test', parts=(Mount(name='g1', content=guide),)))

    child = _assembly_child(assembly)
    size = child.bounding_box().size
    assert size.X == approx(width + 2 * substrate)
    assert size.Y == approx(height + 2 * substrate)
    assert size.Z == approx(3.0)


def test_a_slit_is_drawn_at_its_own_opening():
    importorskip('build123d')
    import scipp as sc
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.brep import to_assembly
    from niess.instrument import Instrument, Mount
    from niess.components import Slit

    slit = Slit(
        name='slit1',
        position=_origin(),
        orientation=_identity(),
        width=sc.scalar(0.05, unit='m'),
        height=sc.scalar(0.03, unit='m'),
    )

    assembly = to_assembly(Instrument(
        name='slit_test', parts=(Mount(name='slit1', content=slit),)))

    child = _assembly_child(assembly)
    size = child.bounding_box().size
    assert size.X == approx(0.05)
    assert size.Y == approx(0.03)
    assert size.Z > 0.0


def test_a_filter_is_drawn_at_its_own_size():
    importorskip('build123d')
    import scipp as sc
    from mccode_antlr import Flavor
    from mccode_antlr.assembler import Assembler
    from niess.brep import to_assembly
    from niess.instrument import Instrument, Mount
    from niess.components import NCrystalFilter

    filt = NCrystalFilter(
        name='f1',
        position=_origin(),
        orientation=_identity(),
        width=sc.scalar(0.4, unit='m'),
        height=sc.scalar(0.2, unit='m'),
        length=sc.scalar(0.1, unit='m'),
        composition='Al_sg225',
        temperature=sc.scalar(300.0, unit='K'),
    )

    assembly = to_assembly(Instrument(
        name='filter_test', parts=(Mount(name='f1', content=filt),)))

    child = _assembly_child(assembly)
    size = child.bounding_box().size
    assert size.X == approx(0.4)
    assert size.Y == approx(0.2)
    assert size.Z == approx(0.1)
