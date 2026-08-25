"""A ring of radial slits about a sample.

BIFROST's is not there to shape the beam. It is how a neutron leaving the sample gets
tagged with the channel it entered: the emitted component reports which opening a
neutron passed, and everything downstream is gated on that. So it is a real aperture
that happens to be used for bookkeeping, not a piece of bookkeeping that happens to look
like an aperture -- which is why it belongs in the tree.

It was emitted directly by ``Tank``'s McStas hook until now, so it existed only in the
McStas conversion. Nothing else could see it: not the NeXus file, which should describe
it, and not a CAD export, which should draw it.
"""
from __future__ import annotations

from scipp import Variable

from .component import Component


class RadialSlitBank(Component):
    """Openings at fixed angles about a sample, all the same width.

    Parameters
    ----------
    angles:
        Where each opening sits, as an angle about the vertical.
    width:
        The angular width they share. A neutron within half of this of an opening's
        angle passes through it.
    radius:
        How far from the sample the openings sit.
    height:
        How tall they are.
    """
    angles: Variable
    width: Variable
    radius: Variable
    height: Variable
    #: Stem of the two run-time knob names, if they are not the component's own name.
    #: BIFROST's bank is called `slits` and its knobs `slitAngle` and `slitDistance`.
    stem: str = None

    def knob(self, suffix: str) -> str:
        return f'{self.stem or self.name}{suffix}'

    def count(self) -> int:
        return int(self.angles.sizes[self.angles.dims[0]])

    def positions_name(self) -> str:
        """The DECLARE'd C array the emitted component reads its angles from."""
        return f'{self.name}_positions'

    def __mccode__(self) -> tuple[str, dict]:
        """The angles reach McStas as a declared array, not as a parameter.

        ``offset`` and ``radius`` are named rather than valued: both are run-time knobs,
        so that a calibration run can sweep a narrow slit across what is behind it.
        """
        return 'Slit_radial_multi', {
            'slit_width': self.width.to(unit='radian').value,
            'offset': f'{self.knob("Angle")}*DEG2RAD',
            'number': self.count(),
            'radius': self.knob('Distance'),
            'height': self.height.to(unit='m').value,
            'positions': self.positions_name(),
        }

    def to_mccode(self, assembler, at=None, rotate=None,
                  insert_provenance_metadata: bool = True):
        """Emit the component, and everything in the instrument it needs.

        The two run-time knobs, the array of angles, the per-particle variable it writes
        and the EXTEND that writes it. All of it is McStas: another target describes the
        openings and has nothing to say about how a simulation records which one a
        neutron took.
        """
        from ..assembler import ensure_registry, ensure_runtime_line, ensure_user_var

        ensure_registry(assembler, 'mcdotstar/mcstas-slit-radial@main')
        ensure_user_var(assembler, 'int', self.tag_name(),
                        'Secondary spectrometer analyzer cassette index')
        ensure_runtime_line(assembler, f'{self.knob("Angle")}/"degree" = 0.0')
        ensure_runtime_line(
            assembler,
            f'{self.knob("Distance")}/"m" = {self.radius.to(unit="m").value}')
        assembler.declare_array('double', self.positions_name(),
                                self.angles.to(unit='radian').values.tolist(),
                                source=__file__, line=0)

        instance = super().to_mccode(
            assembler, at=at, rotate=rotate,
            insert_provenance_metadata=insert_provenance_metadata)
        # `slit` is >= 0 iff the neutron passed one of the openings
        instance.EXTEND(f'{self.tag_name()} = (SCATTERED) ? 1 + slit : -1;')
        return instance

    def tag_name(self) -> str:
        """The per-particle variable recording which opening a neutron took."""
        return 'secondary_cassette'

    def __nexus_leaf__(self, visit):
        """A ring of openings, as an NXslit."""
        from ..targets.nexus import component_body, emit
        from ..nexus.nodes import dataset

        emit(visit, component_body('NXslit', [
            dataset('description', f'{self.count()} radial slits'),
            dataset('x_gap', float(self.width.to(unit='radian').value),
                    attrs={'units': 'radian'}),
            dataset('y_gap', float(self.height.to(unit='m').value),
                    attrs={'units': 'm'}),
            # both are knobs a calibration run sweeps, so the file links to them
            visit.context.linked_log('distance', self.knob('Distance'),
                               attrs={'units': 'm'}),
            visit.context.linked_log('offset', self.knob('Angle'),
                               attrs={'units': 'degrees'}),
            dataset('angles', [float(v) for v in
                               self.angles.to(unit='radian').values],
                    dtype='double', attrs={'units': 'radian'}),
        ]))
        return None
