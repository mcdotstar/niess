"""Write one glTF model per kind of solid niess draws, for the CAD gallery page.

Each is taken from a real instrument's assembly by its label -- the drawing a STEP export
of that instrument contains, not one made up for the picture. The documentation build
runs this into ``docs/assets/cad-gallery`` before building the site:

    python docs/examples/cad_gallery.py docs/assets/cad-gallery
"""
import sys
from copy import copy
from pathlib import Path

#: (file, title, instrument, label, what it shows) -- the gallery page lists the same files
GALLERY = (
    ('moderator', 'ESS butterfly moderator', 'bifrost', 'moderator',
     "ESS_butterfly's outline for BIFROST's beam port, W4, as tall as the moderator"),
    ('elliptic_guide', 'Elliptic guide', 'bifrost', 'nboa',
     "BIFROST's neutron beam optics assembly: four substrate walls following the ellipse"),
    ('straight_guide', 'Straight guide', 'bifrost', 'unit_3_curved_guide_0',
     "One segment of BIFROST's curved guide"),
    ('nx_disk_chopper', 'Disc chopper (NXdisk_chopper)', 'bifrost', 'pulse_shaping_chopper_1',
     "A pulse-shaping disc: one opening, centred on the beam at the disc's reference angle"),
    ('disc_chopper', 'Disc chopper (DiskChopper)', 'teaching', 'chopper',
     "The teaching instrument's single-opening disc"),
    ('jaw', 'Jaws', 'bifrost', 'divergence_slit_1', 'A divergence slit, drawn at its opening'),
    ('slit', 'Slit', 'bifrost', 'mask', "The sample-area mask, drawn at its opening"),
    ('attenuator', 'Attenuator', 'bifrost', 'attenuator_1', 'A filter-style block at its size'),
    ('radial_collimator', 'Radial collimator', 'bifrost', 'wedge_0',
     'One wedge of the tank: the beryllium filter and collimator arcs'),
    ('analyzer', 'Rowland analyzer', 'bifrost', 'channel_1_1_analyzer',
     'Each blade on the Rowland circle through sample, analyzer and detector, turned to focus'),
    ('triplet', 'Detector triplet', 'bifrost', 'channel_1_1_detector',
     'Three He-3 tubes'),
    ('named_position', 'Named position', 'bifrost', 'sample_origin',
     'Three short axes, for a bare Component that marks a place'),
    ('tank', "BIFROST's secondary spectrometer", 'bifrost', 'tank',
     'Nine channels of radial collimators, analyzers and triplets, at a4 = 0'),
)


def instruments():
    from niess.bifrost import bifrost
    from niess.instrument import Instrument, Mount
    from niess.teaching import Primary
    return {
        'bifrost': bifrost.BIFROST,
        'teaching': Instrument(name='teaching', parts=(
            Mount(name='primary', content=Primary.from_calibration()),)),
    }


def find(shape, label):
    """The first part of an assembly with ``label``, depth first."""
    if shape.label == label:
        return shape
    for child in shape.children:
        found = find(child, label)
        if found is not None:
            return found
    return None


def main(outdir: Path) -> None:
    import build123d as bd
    from niess.brep import to_assembly

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    assemblies = {name: to_assembly(instrument) for name, instrument in instruments().items()}
    for file, _, instrument, label, _ in GALLERY:
        part = find(assemblies[instrument], label)
        assert part is not None, f'{instrument} has no part labelled {label!r}'
        # build123d writes nothing for a shape still attached to an assembly
        part = copy(part)
        part.parent = None
        # export_gltf turns CAD's z-up to glTF's y-up; niess is McStas-y-up already
        part.location = part.location * bd.Location((0, 0, 0), (1, 0, 0), 90)
        path = outdir / f'{file}.glb'
        # build123d works in metres here, so no scaling; a coarser tessellation than the
        # default keeps the tank's models a few MB rather than tens
        assert bd.export_gltf(part, path, unit=bd.Unit.M, binary=True,
                              linear_deflection=1e-3, angular_deflection=0.2)
        assert path.stat().st_size > 1000, f'{path.name} has no meshes'  # empty is 240 B


if __name__ == '__main__':
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path('.'))
