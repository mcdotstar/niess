"""How a niess object shows itself, in a terminal and in a notebook.

msgspec generates a repr from the fields, and a composite's fields are its whole subtree:
a BIFROST `Tank` comes out at a quarter of a million characters of nested scipp
variables. Typing the name of the thing you are working on should not flood the terminal,
and it should not be the reason you reach for `dir()`.

So a node shows what it is, what it contains and how big that is. In a notebook the same
tree is `<details>` elements -- collapsed, because the point of a tree with a thousand
nodes is that you open the part you care about, and `<details>` is the one disclosure
widget that needs no javascript and survives nbconvert.

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
    for its size, and answering without one re-counts each subtree once per ancestor:
    BIFROST's notebook tree went from 225 ms to a tenth of that. Held for the length of
    one render, so the ids cannot go stale under it -- the tree is alive throughout.
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


def _line(label: str, node, annotation: str = '', width: int = 0,
          cache: dict | None = None) -> str:
    kind = type(node).__name__
    own = describe(node)
    # a component's own name is worth showing only when it is not already the label
    if own and own != label:
        kind = f'{kind} {own!r}'
    rest = '  '.join(x for x in (kind, size_text(node, cache), annotation) if x)
    return f'{label:{width}s}  {rest}'.rstrip()


def text_tree(node, *, header: str, annotate=None, depth: int = TEXT_DEPTH) -> str:
    """A node and its children, indented, to ``depth`` levels.

    ``annotate`` is called with ``(label, child)`` and may add a phrase to that child's
    line -- what an `Instrument` uses to say where a part hangs.
    """
    lines = [header]
    cache: dict = {}

    def render(current, prefix: str, level: int) -> None:
        kids = children_of(current)
        shown = kids[:TEXT_CHILDREN]
        # one column per sibling group, so the classes line up under each other
        width = max((len(label) for label, _ in shown), default=0)
        for label, child in shown:
            extra = annotate(label, child) if annotate is not None and level == 0 else ''
            lines.append(prefix + _line(label, child, extra, width, cache))
            if level + 1 < depth:
                render(child, prefix + '  ', level + 1)
        if len(kids) > len(shown):
            lines.append(f'{prefix}... {len(kids) - len(shown)} more')

    render(node, '  ', 0)
    return '\n'.join(lines)


def html_tree(node, *, header: str, annotate=None) -> str:
    """The same tree as nested ``<details>``, collapsed below the top level."""
    parts = ['<details open><summary>', header, '</summary>',
             '<div style="margin-left:1em">']
    cache: dict = {}

    def render(current, level: int) -> None:
        kids = children_of(current)
        width = max((len(label) for label, _ in kids), default=0)
        for label, child in kids:
            extra = annotate(label, child) if annotate is not None and level == 0 else ''
            summary = escape(_line(label, child, extra, width, cache))
            summary = summary.replace('  ', '&nbsp;&nbsp;')
            if children_of(child):
                parts.extend(['<details><summary>', summary, '</summary>',
                              '<div style="margin-left:1em">'])
                render(child, level + 1)
                parts.append('</div></details>')
            else:
                parts.append(f'<div>{summary}</div>')

    render(node, 0)
    parts.append('</div></details>')
    return ''.join(parts)


def node_header(node, cache: dict | None = None) -> str:
    """The top line for a plain component or composite."""
    own = describe(node)
    name = f' {own!r}' if own else ''
    size = size_text(node, cache)
    return f'{type(node).__name__}{name}' + (f': {size}' if size else '')
