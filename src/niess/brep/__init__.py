"""Solid geometry -- STEP/CAD -- from a niess instrument.

    from niess.instrument import Instrument, Mount
    from niess.brep import save_step

    save_step(instrument, 'instrument.step')

Reads the tree: a component's position and orientation are on the component, as scipp
Variables, and composing them with the frame it hangs from is arithmetic. Drawing an
instrument niess did *not* build means reading an emitted one instead, which is
`niess.brep.via_instr` and is not imported here -- it is the older route, kept for files
niess did not write.

Importing this module registers the shape builders, which is what `to_assembly` resolves
against.
"""
from __future__ import annotations

from .assembly import BREP_REGISTRY, NiessBRepRegistry, Subject, save_step, to_assembly
# Registers every builder on BREP_REGISTRY. Imported for that side effect: without it
# to_assembly resolves nothing and cheerfully returns an assembly of placeholder cubes.
from . import builders as _builders  # noqa: F401

__all__ = [
    'BREP_REGISTRY',
    'NiessBRepRegistry',
    'Subject',
    'save_step',
    'to_assembly',
]
