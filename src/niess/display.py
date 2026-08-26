"""How a niess object shows itself, in a terminal and in a notebook.

msgspec generates a repr from the fields, and a composite's fields are its whole subtree:
a BIFROST `Tank` comes out at a quarter of a million characters of nested scipp
variables. Typing the name of the thing you are working on should not flood the terminal,
and it should not be the reason you reach for `dir()`.

So a node shows what it is, what it contains and how big that is, in columns aligned
across each set of siblings. In a notebook the same tree is `<details>` elements --
collapsed, because the point of a tree with a thousand nodes is that you open the part
you care about, and `<details>` is the one disclosure widget that needs no javascript and
survives nbconvert.

Parameters are shown when there are few enough things to show them for. A whole
instrument lists its parts; one chopper lists its radius, its speed and where it sits --
which is the question being asked by whoever reached for one chopper. `PARAMETERS`
overrides that judgement either way, and `show()` takes it per call.

Written against `__niess_children__` rather than against a base class, because the two
roots do not share one: `Base` is what components and composites derive from, `Section`
is a separate `msgspec.Struct`, and a user holds one of each without knowing or caring.
`niess.tree` makes the same choice for the same reason.
"""
from __future__ import annotations

from html import escape

#: How many children to list in a text repr before saying how many are left. A BIFROST
#: tank has nine channels and each five arms, so a handful shows the shape; the rest is
#: the same thing again and is a scroll rather than an answer.
TEXT_CHILDREN = 12

#: How deep a text repr goes. One level is what "what is in this?" means; deeper is what
#: the notebook tree is for.
TEXT_DEPTH = 1

#: Show parameters for a node containing no more than this many things. One chopper is
#: 1; the teaching primary is 7; BIFROST is 772 and lists its parts instead.
PARAMETER_LIMIT = 16

#: How much of one node's parameters fits on its line inside a tree. The node being
#: displayed itself is not truncated -- that is the one that was asked for.
PARAMETER_WIDTH = 72

#: ``None`` to decide by size, ``True`` or ``False`` to insist. A module-level flag
#: rather than an argument because ``repr()`` takes none; ``show()`` takes it per call.
PARAMETERS: bool | None = None

_MONO = 'ui-monospace,SFMono-Regular,Menlo,Consolas,monospace'

#: The columns after the class name are context rather than identity, so they are muted
#: by opacity rather than by a fixed grey -- which would vanish against one notebook
#: theme or the other.
_DIM = 'opacity:.65'


def children_of(node) -> tuple:
    """``(label, child)`` pairs, or empty when this is not a niess node at all."""
    getter = getattr(node, '__niess_children__', None)
    if getter is None:
        return ()
    try:
        return tuple(getter())
    except Exception:
        # a node that cannot say what it contains still has to be printable
        return ()


def is_node(value) -> bool:
    return hasattr(value, '__niess_children__')


def leaf_count(node, cache: dict | None = None) -> int | None:
    """How many things this node contains that emit, or ``None`` if it cannot be walked.

    Leaves rather than nodes, because that is the number meant by "how big is this?".
    ``None`` says the object is not a niess tree node -- it has no
    ``__niess_children__``, so no target can read it either, and a repr that quietly
    reported ``0`` would be hiding that.

    ``cache`` is keyed on object identity and exists because rendering asks every node
    for its size, and answering without one re-counts each subtree once per ancestor.
    Held for the length of one render, so the ids cannot go stale under it -- the tree
    is alive throughout.
    """
    if not is_node(node):
        return None
    if cache is not None and id(node) in cache:
        return cache[id(node)]
    kids = children_of(node)
    if not kids:
        total = 1
    else:
        total = 0
        for _, child in kids:
            count = leaf_count(child, cache)
            total += 1 if count is None else count
    if cache is not None:
        cache[id(node)] = total
    return total


def describe(node) -> str:
    """A node's own name, when it has one worth showing."""
    name = getattr(node, 'name', None)
    return str(name) if isinstance(name, str) and name else ''


def size_text(node, cache: dict | None = None) -> str:
    """How big a node is, as it reads on the end of a line."""
    count = leaf_count(node, cache)
    if count is None:
        return 'not a niess tree node'
    if not children_of(node):
        return ''
    return f'{count} component(s)'


# -- parameters ------------------------------------------------------------------
#
# Short, or there is no point: a scipp variable's own repr is three lines of table.

def value_text(value) -> str | None:
    """One field's value in as few characters as it can be said in.

    ``None`` for anything not worth a column: an unset optional, an identity rotation,
    a child -- which the tree shows anyway.
    """
    if value is None or is_node(value):
        return None
    if hasattr(value, 'dims') and hasattr(value, 'unit'):
        return _variable_text(value)
    name = getattr(value, 'name', None)
    if name is not None and hasattr(value, 'value'):
        return str(name)  # an InstrumentParameter is the knob's name
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        return f'{value:g}'
    if isinstance(value, str):
        return repr(value)
    if isinstance(value, (list, tuple)):
        # a sequence of children is the tree below this line, not a parameter of it
        if any(is_node(item) for item in value):
            return None
        return f'[{len(value)}]'
    return None


def _variable_text(variable) -> str | None:
    """A scipp variable, short. ``None`` when it says nothing worth the space."""
    unit = '' if str(variable.unit) == 'dimensionless' else f' {variable.unit}'
    kind = str(variable.dtype)
    if variable.dims:
        return f'[{"x".join(str(n) for n in variable.shape)}]{unit}'
    if kind == 'vector3':
        return '(' + ', '.join(f'{float(v):g}' for v in variable.value) + f'){unit}'
    if kind == 'rotation3':
        # an identity rotation is the default and says nothing; anything else is worth
        # knowing about, but not worth four numbers on a summary line
        try:
            same = bool((variable.value == [0., 0., 0., 1.]).all())
        except Exception:
            same = False
        return None if same else 'rotated'
    try:
        return f'{float(variable.value):g}{unit}'
    except Exception:
        return None


def parameter_text(node) -> str:
    """A node's own fields -- what it is, as opposed to what it contains."""
    from .tree import component_fields
    try:
        fields = component_fields(node)
    except Exception:
        return ''
    pairs = []
    for field in fields:
        if field.name == 'name':
            continue  # already the label
        try:
            text = value_text(getattr(node, field.name))
        except Exception:
            text = None
        if text is not None:
            pairs.append(f'{field.name}={text}')
    return ', '.join(pairs)


def wanted(node, cache: dict | None = None) -> bool:
    """Whether to show parameters at all for this display."""
    if PARAMETERS is not None:
        return PARAMETERS
    count = leaf_count(node, cache)
    return count is not None and count <= PARAMETER_LIMIT


def _clip(text: str, width: int) -> str:
    return text if len(text) <= width else text[:width - 1] + '…'


# -- layout ----------------------------------------------------------------------

def _cells(label: str, node, annotation: str, show_parameters: bool,
           cache: dict | None = None) -> list[str]:
    """One row as columns, so a set of siblings can be aligned against each other."""
    kind = type(node).__name__
    own = describe(node)
    if own and own != label:
        kind = f'{kind} {own!r}'
    parameters = (_clip(parameter_text(node), PARAMETER_WIDTH)
                  if show_parameters else '')
    return [label, kind, size_text(node, cache), annotation, parameters]


def _widths(rows: list[list[str]]) -> list[int]:
    """The label and class columns, each sized to the widest of its siblings."""
    return [max((len(row[i]) for row in rows), default=0) for i in range(2)]


def _row(cells: list[str], widths: list[int]) -> str:
    padded = [cell.ljust(width) for cell, width in zip(cells[:2], widths)]
    return '  '.join(padded + [c for c in cells[2:] if c]).rstrip()


def _html_row(cells: list[str], widths: list[int], seen: set) -> str:
    """The same row, as boxes.

    A summary line is HTML, where runs of spaces collapse -- so the columns are
    ``ch``-width inline blocks. Only a real box lines up with the box above it.

    The widths go into ``seen`` and come back as classes rather than as an inline style
    on every span: BIFROST is a thousand rows, and repeating the same forty characters
    of CSS on each of them was two thirds of the output.
    """
    label, kind, size, annotation, parameters = cells
    boxes = []
    for text, width in ((label, widths[0] + 2), (kind, widths[1] + 2)):
        seen.add(width)
        boxes.append(f'<span class="niess-c niess-w{width}">{escape(text)}</span>')
    trailing = '&nbsp;&nbsp;'.join(escape(t) for t in (size, annotation, parameters) if t)
    if trailing:
        boxes.append(f'<span class="niess-d">{trailing}</span>')
    return ''.join(boxes)


def _stylesheet(widths: set) -> str:
    """One rule per column width this tree actually used.

    Class names are prefixed because a ``<style>`` in notebook output is not scoped to
    the cell that produced it.
    """
    rules = [f'.niess-tree{{font-family:{_MONO};line-height:1.45}}',
             '.niess-tree .niess-c{display:inline-block}',
             f'.niess-tree .niess-d{{{_DIM}}}']
    rules += [f'.niess-tree .niess-w{w}{{min-width:{w}ch}}' for w in sorted(widths)]
    return '<style>' + ''.join(rules) + '</style>'


def node_header(node, cache: dict | None = None,
                show_parameters: bool | None = None) -> str:
    """The top line: what this is, how big, and its own fields.

    Not truncated, unlike a row inside the tree -- this is the object that was asked
    for, and the fields are most of the answer for a component with no children.
    """
    own = describe(node)
    name = f' {own!r}' if own else ''
    size = size_text(node, cache)
    head = f'{type(node).__name__}{name}' + (f': {size}' if size else '')
    if show_parameters is None:
        show_parameters = wanted(node, cache)
    parameters = parameter_text(node) if show_parameters else ''
    return f'{head}  {parameters}'.rstrip() if parameters else head


def text_tree(node, *, header: str, annotate=None, depth: int = TEXT_DEPTH,
              parameters: bool | None = None) -> str:
    """A node and its children, in aligned columns, to ``depth`` levels.

    ``annotate`` is called with ``(label, child)`` and may add a phrase to that child's
    line -- what an `Instrument` uses to say where a part hangs.
    """
    lines = [header]
    cache: dict = {}
    show_parameters = wanted(node, cache) if parameters is None else parameters

    def render(current, prefix: str, level: int) -> None:
        kids = children_of(current)
        shown = kids[:TEXT_CHILDREN]
        rows = [_cells(label, child,
                       annotate(label, child) if annotate and level == 0 else '',
                       show_parameters, cache)
                for label, child in shown]
        widths = _widths(rows)
        for (label, child), cells in zip(shown, rows):
            lines.append(prefix + _row(cells, widths))
            if level + 1 < depth:
                render(child, prefix + '  ', level + 1)
        if len(kids) > len(shown):
            lines.append(f'{prefix}… {len(kids) - len(shown)} more')

    render(node, '  ', 0)
    return '\n'.join(lines)


def html_tree(node, *, header: str, annotate=None,
              parameters: bool | None = None) -> str:
    """The same tree as nested ``<details>``, collapsed below the top level."""
    cache: dict = {}
    show_parameters = wanted(node, cache) if parameters is None else parameters
    seen: set = set()
    parts = ['<div class="niess-tree">',
             '<details open><summary>', header, '</summary>',
             '<div style="margin-left:1em">']

    def render(current, level: int) -> None:
        kids = children_of(current)
        rows = [_cells(label, child,
                       annotate(label, child) if annotate and level == 0 else '',
                       show_parameters, cache)
                for label, child in kids]
        widths = _widths(rows)
        for (label, child), cells in zip(kids, rows):
            summary = _html_row(cells, widths, seen)
            if children_of(child):
                parts.extend(['<details><summary>', summary, '</summary>',
                              '<div style="margin-left:1em">'])
                render(child, level + 1)
                parts.append('</div></details>')
            else:
                # the indent lines a childless row up with its openable siblings, which
                # carry a disclosure triangle it has no use for
                parts.append(f'<div style="margin-left:1.1em">{summary}</div>')

    render(node, 0)
    parts.append('</div></details></div>')
    return _stylesheet(seen) + ''.join(parts)


def show(node, *, parameters: bool | None = None, depth: int = TEXT_DEPTH) -> str:
    """The text tree for any niess node, with the judgement calls made explicit.

        print(show(chopper, parameters=True))
        print(show(tank, depth=2))
    """
    cache: dict = {}
    return text_tree(node, header=node_header(node, cache, parameters),
                     depth=depth, parameters=parameters)
