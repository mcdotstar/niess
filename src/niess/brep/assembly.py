"""Solid geometry, built from the tree.

`via_instr` hands the same shape builders to `mccode_antlr`'s renderer, which walks an
emitted instrument and places each shape in the global frame. That placement has never
worked: it is computed inside a `try` whose `except Exception: pass` discarded a
`TypeError` raised for every component, so every solid was exported at the origin and a
162 m instrument came out 4.4 m long. The fix belongs upstream and is written, but a
released mccode-antlr will not have it, and niess should not ship a CAD export that
produces a heap of parts either way.

Building from the tree needs none of it. A component's position and orientation are on
the component, as scipp Variables; a frame is a declared node; and composing the two is
arithmetic rather than expression evaluation.

The builders themselves are unchanged in substance. They were always written against the
McCode parameters a component reports -- which is what ``__mccode__`` returns -- so they
keep taking those, from the object rather than from an emitted instance.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..dispatch import NiessRegistry
from ..walk import Context, Visit, walk


class NiessBRepRegistry(NiessRegistry):
    """Shape-builder lookup for the CAD target.

    Resolves either way: :meth:`resolve_for_object` for a niess object the walk handed
    over, :meth:`resolve_builder` for an emitted instance. The builders take a
    :class:`Subject` and do not know which happened.
    """

    def __init__(self, parent=None):
        super().__init__(parent=parent, hooks='brep')


BREP_REGISTRY = NiessBRepRegistry()


def _identity_placement():
    from scipp import vector
    from scipp.spatial import rotations_from_rotvecs
    return (vector([0., 0., 0.], unit='m'),
            rotations_from_rotvecs(vector([0., 0., 0.], unit='degree')))


@dataclass
class BRepContext(Context):
    """Where each node sits, composed as the walk descends."""
    shapes: list = field(default_factory=list)
    placements: dict = field(default_factory=dict)

    def placement_of(self, frame):
        """The global placement of a frame, or the instrument origin for none.

        Looked up by tree path or by emitted name: a declared frame is referred to by
        path, while a Mount's ``relative_to`` names a component.
        """
        if frame is None:
            return _identity_placement()
        return self.placements.get(frame, _identity_placement())

    def place(self, visit: Visit, position, orientation):
        """Compose a local placement onto the frame it sits in, and record it."""
        base_position, base_rotation = self.placement_of(visit.frame)
        composed = (base_position + base_rotation * position.to(unit='m'),
                    base_rotation * orientation)
        self.placements[visit.id] = composed
        self.placements[visit.name] = composed
        return composed


@dataclass
class Subject:
    """What a shape builder is given, whichever route it was reached by.

    The builders were always written against the McCode parameters a component reports,
    so that is what they still take. ``obj`` is the niess object when there is one --
    reading a dimension off it beats reading the four edges it emits as -- and ``None``
    when the shape is being built from an emitted instance instead.
    """
    name: str
    params: dict
    obj: Any = None
    #: Provenance extras, when the shape is being built from an emitted instance. That
    #: is a documented extension point -- tagging an instance with a `substrate` or a
    #: `width` is how an instrument says something the McCode parameters do not -- and
    #: reading the object says the same thing more directly.
    extra: dict = field(default_factory=dict)


def mccode_parameters(obj) -> dict[str, float]:
    """The numbers a component reports about itself.

    ``__mccode__`` is where a component says what it is and how big -- the same
    dictionary that reaches the emitted instrument, which is where the shape builders
    have always read their dimensions from. Anything not a number is a run-time knob
    and is left out, as it is on the other route.
    """
    try:
        _, parameters = obj.__mccode__()
    except Exception:
        return {}
    found = {}
    for name, value in parameters.items():
        try:
            found[name] = float(value)
        except (TypeError, ValueError):
            continue
    return found


def _located(shape, position, orientation):
    """Put a shape where it belongs, from a scipp position and rotation."""
    import build123d as bd
    from scipp import vector

    columns = [orientation * vector(axis, unit='dimensionless')
               for axis in ([1., 0., 0.], [0., 0., 1.])]
    x_dir = tuple(float(v) for v in columns[0].value)
    z_dir = tuple(float(v) for v in columns[1].value)
    origin = tuple(float(v) for v in position.to(unit='m').value)
    return shape.locate(bd.Location(bd.Plane(origin=origin, x_dir=x_dir, z_dir=z_dir)))


def _local_placement(visit: Visit):
    """Where a node sits within the frame it hangs from.

    A frame states its own offset and turn; a component carries a measured position and
    orientation; a composite with neither sits at its frame's origin.
    """
    from ..components.frame import Frame

    obj = visit.obj
    if isinstance(obj, Frame):
        return obj.position, obj.orientation()
    if hasattr(obj, 'position') and hasattr(obj, 'orientation'):
        return obj.position, obj.orientation
    return _identity_placement()


def to_assembly(instrument, registry=None):
    """Build a labelled ``build123d`` Compound of everything with a shape.

    Every node is placed, whether or not it has a shape: a frame draws nothing and is
    still what the things hanging from it are measured against.
    """
    import build123d as bd
    from ..walk import visits

    resolver = BREP_REGISTRY if registry is None else registry
    context = BRepContext(instrument=instrument)

    for visit in visits(instrument):
        visit.context = context
        position, orientation = context.place(visit, *_local_placement(visit))
        builder = resolver.resolve_for_object(visit.obj)
        if builder is None:
            continue
        shape = builder(Subject(name=visit.name, obj=visit.obj,
                                params=mccode_parameters(visit.obj)))
        if shape is None:
            continue
        shape.label = visit.name
        context.shapes.append(_located(shape, position, orientation))

    if not context.shapes:
        return bd.Compound([bd.Box(1e-3, 1e-3, 1e-3)])
    return bd.Compound(context.shapes)


def save_step(instrument, path, registry=None) -> None:
    """Write an instrument to a STEP file."""
    from mccode_antlr.display.render.brep import save_step as write
    write(to_assembly(instrument, registry=registry), path)
