"""Write a NeXus translator for a component, and scope it to one conversion.

The teaching instrument's jaw converts to a generic NXaperture. Suppose this
instrument's jaw is really a beam-defining diaphragm that downstream tooling expects as
an NXslit with its own opening datasets: that is a translator plus a registry.
"""
from pathlib import Path


def main(outdir: Path) -> None:
    from niess.instrument import Instrument, Mount
    from niess.teaching import Primary

    # --8<-- [start:registry]
    from niess.components.aperture import Jaw
    from niess.nexus.nodes import dataset
    from niess.targets.nexus import (
        NEXUS_REGISTRY, NiessNexusRegistry, component_body, emit,
    )

    # Extend the default registry rather than modifying it, so these translators apply
    # only to conversions that ask for this one.
    TEACHING_REGISTRY = NiessNexusRegistry(parent=NEXUS_REGISTRY)

    @TEACHING_REGISTRY.register(Jaw)
    class DiaphragmTranslator:
        """A Jaw as an NXslit carrying its run-time opening."""

        @staticmethod
        def leaf(visit):
            jaw = visit.obj
            edges = jaw.edge_parameters()
            emit(visit, component_body('NXslit', [
                dataset('description', f'beam-defining diaphragm {visit.name}'),
                # the edges are knobs a run sets, so these are links to their NXlogs
                visit.context.linked_log('x_gap', edges['right'], attrs={'units': 'm'}),
                dataset('y_gap', float(jaw.height.to(unit='m').value),
                        attrs={'units': 'm'}),
            ]))
    # --8<-- [end:registry]

    teaching = Instrument(name='teaching', origin='sample_origin', parts=(
        Mount(name='primary', content=Primary.from_calibration()),
    ))

    # --8<-- [start:use]
    from niess.targets.nexus import to_nexus_structure

    structure = to_nexus_structure(teaching, registry=TEACHING_REGISTRY)
    # --8<-- [end:use]

    from niess.nexus.nodes import find_child, get_attribute

    instrument = structure['children'][0]['children'][0]
    jaw = find_child(instrument, 'jaw')
    assert get_attribute(jaw, 'NX_class') == 'NXslit'
    assert find_child(jaw, 'description') is not None
    # jaw_r is an instrument parameter, so x_gap became a link to its NXlog
    assert get_attribute(find_child(jaw, 'x_gap'), 'NX_class') == 'NXlog'

    # The default registry is untouched: the same instrument still converts the old way
    plain = to_nexus_structure(teaching)
    plain_jaw = find_child(plain['children'][0]['children'][0], 'jaw')
    assert get_attribute(plain_jaw, 'NX_class') == 'NXaperture'


if __name__ == '__main__':
    main(Path('.'))
