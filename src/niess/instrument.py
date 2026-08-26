"""The whole instrument, as one object.

Until now there was no such thing. An instrument existed only as a sequence of calls --

    assembler = Assembler('bifrost', flavor=Flavor.MCSTAS)
    Primary.from_calibration(primary_parameters()).to_mccode(assembler)
    Tank.from_calibration(tank_parameters()).to_mccode(assembler, 'sample_origin')

-- so "the whole of BIFROST" was something that happened inside an ``Assembler`` and
nowhere else. Anything wanting to walk an instrument had to be handed the pieces and
told how they fit together, which is why every target's entry point takes an assembled
McStas instrument rather than a niess object.

An ``Instrument`` says it once. It is a tree node like any other, so it walks, it has a
flow graph, and the pieces keep their own identities inside it.
"""
from __future__ import annotations

from typing import Any, Optional

import msgspec
from mccode_antlr import Flavor
from mccode_antlr.common import InstrumentParameter

from .components.component import Base


def _walk(node):
    """Deferred so importing this module does not pull the tree machinery in."""
    from .tree import walk
    return walk(node)


def _count_leaves(content) -> Optional[int]:
    """How many things a part contributes, or ``None`` if it is not a tree node.

    `walk` calls ``__niess_children__`` on everything it reaches, so anything that is
    not a node -- an `IndirectSecondary`, say, which derives from `object` and predates
    the tree protocol -- raises part-way through. That is the right answer for a target,
    which cannot emit what it cannot walk, and the wrong one for a repr.
    """
    from .tree import is_node
    if not is_node(content):
        return None
    try:
        return sum(1 for _, node in _walk(content)
                   if is_node(node) and not node.__niess_children__())
    except Exception:  # a part that will not walk is a part with no count
        return None


def _is_at_origin(content) -> bool:
    """Whether a thing sits at the origin of the frame it hangs from."""
    position = getattr(content, 'position', None)
    if position is None:
        return True
    try:
        return not any(abs(float(v)) > 0 for v in position.to(unit='m').value)
    except Exception:
        return False


def _is_unturned(content) -> bool:
    """Whether a thing is not turned within the frame it hangs from."""
    orientation = getattr(content, 'orientation', None)
    if orientation is None:
        return True
    try:
        from .spatial import mccode_ordered_angles
        turn = orientation() if callable(orientation) else orientation
        return not any(abs(a) > 0 for a in mccode_ordered_angles(turn))
    except Exception:
        return False


def _angle_text(angle) -> str:
    """A mounting angle as it reads: a parameter by name, a number as a number."""
    name = getattr(angle, 'name', None)
    if name is not None:
        return str(name)
    return f'{angle:g}' if isinstance(angle, (int, float)) else str(angle)


class Mount(msgspec.Struct):
    """A top-level piece of an instrument, and the frame it hangs from.

    ``relative_to`` names a component emitted by an earlier piece. BIFROST's tank is
    described in coordinates about the sample -- its first analyzer sits at
    ``[1.189, 0, 0]``, not 162 m down the guide -- so it hangs from ``sample_origin``,
    which the primary provides. A piece whose coordinates are already global, as the
    primary's are, hangs from nothing.

    ``rotation`` turns the piece about the frame it hangs from, in degrees, in McCode's
    ``ROTATED`` order -- the extrinsic x-y-z that :func:`niess.spatial.mccode_ordered_angles`
    documents. Its three entries may be numbers or ``InstrumentParameter``s, because the
    interesting ones are driven at run time: a BIFROST run turns the sample by a3 and
    the detector tank by a4, and neither is known when the instrument is described.

        Mount(name='tank', content=tank, relative_to='sample_origin',
              rotation=(0, a4, 0))

    A parameter here is not a special case downstream. McStas emits an ``Arm`` turned by
    the named parameter and hangs the piece from it; NeXus emits a transformation whose
    value links to that parameter's ``NXlog``, which is what
    :mod:`niess.nexus.expression` already does for any run-time value. So the
    intermediate frame is something a target *emits*, not something an instrument has to
    model -- the same treatment the tank's ninety-nine internal coordinate frames get.

    The name is the path label its contents appear under, so a blade deep inside BIFROST
    is ``tank/channels[2]/pairs[0]/analyzer/blades[3]`` rather than starting at
    ``channels[2]``.
    """

    def is_turned(self) -> bool:
        """Whether this piece is turned at all, rather than merely offset."""
        return self.rotation is not None and any(
            not isinstance(angle, (int, float)) or angle != 0
            for angle in self.rotation
        )

    def __repr__(self) -> str:
        """What is mounted and where, not the whole of it.

        Same reason as `Instrument.__repr__`: the generated one prints `content` in
        full, so reaching for `instrument.parts` floods the terminal.
        """
        text = f'Mount {self.name}: {type(self.content).__name__}'
        where = f' \u2190 {self.relative_to}' if self.relative_to else ''
        if self.is_turned():
            where += f' turned ({", ".join(_angle_text(a) for a in self.rotation)})'
        return text + where

    def frame(self):
        """The coordinate frame this mounting implies, or ``None`` if it implies none.

        A mounting that only says *where* needs no frame -- ``relative_to`` is already a
        frame, and McStas, NeXus and CAD each hang the part off it directly. A mounting
        that says *how it is turned* needs one, because the turn is a statement about
        where to measure the contents from, and that is what a `Frame` is.

        Described once here rather than three times in the targets, which is the whole
        reason `Frame` exists: McStas renders it as an `Arm`, NeXus as a link in a
        ``depends_on`` chain, CAD as a node in the assembly.
        """
        if not self.is_turned():
            return None
        from .components.frame import Frame
        return Frame(name=f'{self.name}_mounting', rotation=tuple(self.rotation),
                     extra={'frame': 'mounting'}, owner_key=None)

    def collapses(self) -> bool:
        """Whether the turn can be written onto the contents instead of an Arm of its own.

        The frame is real either way -- it is in the tree, and NeXus and CAD render it.
        This is about McStas text: an Arm whose only dependent sits at its origin
        unturned says nothing the dependent cannot say itself.

        Only when the contents are one thing that sits *at* the frame's origin and is
        not turned itself. An ``AT`` offset rotates with the frame it is measured in --
        ``AT (0,0,1) RELATIVE`` an arm turned 90 degrees about y resolves to (1,0,0),
        not (0,0,1) -- so pushing a turn onto anything with an offset silently moves it.
        And a composite is not one thing: its contents each hang off the frame, so the
        frame has to exist for them to hang off.
        """
        content = self.content
        if self.frame() is None:
            return False
        children = getattr(content, '__niess_children__', None)
        if children is None or children():
            return False
        return _is_at_origin(content) and _is_unturned(content)

    def parameters(self):
        """The run-time parameters this mounting depends on, if any."""
        from mccode_antlr.common import InstrumentParameter
        if self.rotation is None:
            return ()
        return tuple(angle for angle in self.rotation
                     if isinstance(angle, InstrumentParameter))
    name: str
    content: Any
    relative_to: Optional[str] = None
    rotation: Optional[tuple[Any, Any, Any]] = None


class Instrument(Base):
    """An instrument: what it is called, what it is made of, and what it is for.

    ``origin`` names the component other things are measured against -- the sample
    position. Targets need it and each currently guesses: ``niess.nexus`` looks for a
    component of McStas category ``samples`` and warns when it cannot find one, and
    callers pass ``origin='sample_origin'`` by hand. It is a property of the instrument,
    so it is recorded here.

    ``parameters`` are the knobs a run can turn. They are created during emission today,
    by whichever component happens to want one; holding them here lets an instrument
    declare them up front instead.
    """
    name: str
    parts: tuple[Mount, ...]
    flavor: Flavor = Flavor.MCSTAS
    origin: Optional[str] = None
    parameters: tuple[InstrumentParameter, ...] = ()

    @classmethod
    def of(cls, name: str, **parts):
        """Build from keyword pieces, in the order given.

        ``Instrument.of('bifrost', primary=..., tank=...)`` -- for the common case where
        every piece is either global or hangs from the instrument's own origin. Pass a
        ``Mount`` for anything that needs to say what it hangs from.
        """
        mounted = tuple(
            part if isinstance(part, Mount) else Mount(name=label, content=part)
            for label, part in parts.items()
        )
        return cls(name=name, parts=mounted)

    def __niess_children__(self):
        """The pieces, under their own labels -- the Mount itself is not a node.

        A turned mounting contributes the frame it implies, immediately before what
        hangs off it, unless the turn collapses onto the contents outright.
        """
        found = []
        for mount in self.parts:
            frame = mount.frame()
            if frame is not None:
                found.append((frame.name, frame))
            found.append((mount.name, mount.content))
        return tuple(found)

    def __niess_child_frame__(self, visit, label: str, default):
        """Each piece hangs where its Mount says, not where the one before it did.

        A turned mounting puts its frame in between: the frame hangs where the mounting
        says, and the contents hang off the frame.
        """
        mount = self._mount_for(label)
        if mount is None:
            return default
        if label != mount.name:                       # this is the mounting's own frame
            return mount.relative_to or default
        frame = mount.frame()
        if frame is None:
            return mount.relative_to or default
        return f'{visit.id}/{frame.name}' if visit.id else frame.name

    def __mccode_collapsed__(self, frame_name: str):
        """The turn and reference a collapsed mounting hands to its contents.

        ``None`` when the mounting's frame has to be emitted in its own right, which is
        whenever the contents are more than one thing, or sit anywhere but its origin.
        """
        for mount in self.parts:
            frame = mount.frame()
            if frame is not None and frame.name == frame_name and mount.collapses():
                return frame.mccode_angles(), mount.relative_to
        return None

    def _mount_for(self, label: str):
        """The Mount a child label belongs to -- the part itself, or its frame."""
        for mount in self.parts:
            if label == mount.name:
                return mount
            frame = mount.frame()
            if frame is not None and label == frame.name:
                return mount
        return None

    def mount_parameters(self):
        """Every run-time parameter the mountings depend on, in part order.

        A target emitting the frames has to declare these before naming them. Distinct
        from ``parameters``, which is what the instrument declares of its own accord.
        """
        found = []
        for mount in self.parts:
            for parameter in mount.parameters():
                if parameter not in found:
                    found.append(parameter)
        return tuple(found)

    def summary(self) -> tuple[tuple[str, str, Optional[int]], ...]:
        """Each part as ``(label, class name, component count)``, in beam order.

        The count is leaves -- things that emit -- rather than nodes, because that is
        the number anyone asking "how big is this?" means.

        ``None`` where the part cannot be walked at all, which means it is not a niess
        tree node: it has no ``__niess_children__``, so no target can read it either and
        this instrument will not emit. Reported rather than raised, because the first
        thing anyone does with an object that is not working is look at it, and a repr
        that raises takes that away.
        """
        from .display import leaf_count
        return tuple((mount.name, type(mount.content).__name__,
                      leaf_count(mount.content)) for mount in self.parts)

    def _mounting(self, mount: Mount) -> str:
        """Where a part hangs and how it is turned, as one phrase."""
        where = f'\u2190 {mount.relative_to}' if mount.relative_to else ''
        if not mount.is_turned():
            return where
        angles = ', '.join(_angle_text(a) for a in mount.rotation)
        return f'{where} turned ({angles})'.strip()

    def _annotate(self, label: str, _child) -> str:
        """A top-level part's line says where it hangs; nothing deeper does."""
        try:
            return self._mounting(self.mount_of(label))
        except KeyError:
            return ''

    def _knobs(self) -> tuple[str, ...]:
        """Every run-time parameter this instrument names, declared or mounted."""
        names = [p.name for p in self.parameters]
        for parameter in self.mount_parameters():
            if parameter.name not in names:
                names.append(parameter.name)
        return tuple(names)

    def _header(self) -> str:
        """What this instrument is, before anything it contains."""
        parts = self.summary()
        known = [count for _, _, count in parts if count is not None]
        total = f'{sum(known)}{"+" if len(known) < len(parts) else ""}'
        head = (f'{self.name}: {len(parts)} part(s), {total} component(s)'
                f' [{self.flavor}]')
        if self.origin:
            head += f', origin {self.origin!r}'
        return head

    def __repr__(self) -> str:
        """One screen, not the whole tree.

        msgspec generates a repr from the fields, which for BIFROST is 300 000
        characters of nested scipp variables -- displaying an instrument by accident
        floods the terminal and tells you nothing. This says what it is, what it is made
        of and how big each piece is; :mod:`niess.display` does the same for the pieces.
        """
        from .display import text_tree
        text = text_tree(self, header=self._header(), annotate=self._annotate)
        knobs = self._knobs()
        return text + (f'\n  run-time parameters: {", ".join(knobs)}' if knobs else '')

    def _repr_html_(self) -> str:
        """The whole instrument as a collapsed tree, for a notebook."""
        from html import escape
        from .display import html_tree
        html = html_tree(self, header=f'<b>{escape(self._header())}</b>',
                         annotate=self._annotate)
        knobs = self._knobs()
        if knobs:
            named = ', '.join(f'<code>{escape(k)}</code>' for k in knobs)
            html += f'<div>run-time parameters: {named}</div>'
        return html

    def mount_of(self, label: str) -> Mount:
        """The Mount a top-level piece arrived in."""
        for mount in self.parts:
            if mount.name == label:
                return mount
        raise KeyError(f'{self.name} has no part called {label!r}')
