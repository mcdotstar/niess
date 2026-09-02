"""NeXus Structure JSON node constructors.

Every node this package builds is a plain JSON-compatible ``dict`` in the schema
the ESS kafka-to-nexus filewriter consumes:

* group   -- ``{'name':.., 'type':'group', 'attributes':[..], 'children':[..]}``
* dataset -- ``{'module':'dataset', 'config':{'name':.., 'values':.., 'type':..}}``
* stream  -- ``{'module':'ev44'|'da00'|'link'|.., 'config':{..}}``

There is deliberately no intermediate object model: what a translator builds is
what gets serialized.
"""
from __future__ import annotations

from typing import Any


def attribute(name: str, values, dtype: str | None = None) -> dict:
    if dtype is None:
        dtype, values = convert_type(values)
    return {'name': name, 'dtype': dtype, 'values': values}


def _attributes(nx_class: str | None, attrs: dict[str, Any] | None) -> list[dict]:
    out = []
    if nx_class is not None:
        out.append(attribute('NX_class', nx_class, dtype='string'))
    for name, value in (attrs or {}).items():
        out.append(attribute(name, value))
    return out


def group(
        name: str,
        nx_class: str | None = None,
        children: list | None = None,
        attrs: dict[str, Any] | None = None,
) -> dict:
    node = {'name': name, 'type': 'group'}
    if children:
        node['children'] = list(children)
    attributes = _attributes(nx_class, attrs)
    if attributes:
        node['attributes'] = attributes
    return node


def dataset(name: str, values, dtype: str | None = None, attrs: dict[str, Any] | None = None) -> dict:
    if dtype is None:
        dtype, values = convert_type(values)
    node = {'module': 'dataset', 'config': {'name': name, 'values': values, 'dtype': dtype}}
    attributes = _attributes(None, attrs)
    if attributes:
        node['attributes'] = attributes
    return node


def stream(module: str, config: dict, attrs: dict[str, Any] | None = None) -> dict:
    """A filewriter module directive -- ``ev44``, ``da00``, ``f144``, ``link``, ..."""
    node = {'module': module, 'config': config}
    attributes = _attributes(None, attrs)
    if attributes:
        node['attributes'] = attributes
    return node


def is_group(node) -> bool:
    return isinstance(node, dict) and node.get('type') == 'group'


def is_dataset(node) -> bool:
    return isinstance(node, dict) and node.get('module') == 'dataset'


def node_name(node) -> str | None:
    """The name of a group, dataset, or named stream node."""
    if not isinstance(node, dict):
        return None
    if 'name' in node:
        return node['name']
    return (node.get('config') or {}).get('name')


def children_of(node) -> list:
    return node.get('children') or []


def add_child(node: dict, child) -> dict:
    node.setdefault('children', []).append(child)
    return node


def add_attribute(node: dict, name: str, values, dtype: str | None = None) -> dict:
    node.setdefault('attributes', []).append(attribute(name, values, dtype=dtype))
    return node


def get_attribute(node, name: str):
    for attr in (node.get('attributes') or []):
        if attr.get('name') == name:
            return attr.get('values')
    return None


def find_child(node, name: str):
    for child in children_of(node):
        if node_name(child) == name:
            return child
    return None


_DTYPE_ALIASES = {
    'str': 'string',
    'float64': 'double',
    'float': 'double',
    'int': 'int64',
}


def convert_type(obj) -> tuple[str, Any]:
    """Map a Python/numpy value onto a NeXus Structure ``(dtype, values)`` pair.

    Ported from ``moreniius.writer.convert_types`` minus its ``nexusformat``
    branches, which no longer have anything to unwrap.
    """
    from numpy import dtype as np_dtype, ndarray, generic

    if isinstance(obj, ndarray):
        return _array_type(obj.tolist(), obj.dtype.name)
    if isinstance(obj, (list, tuple)):
        from numpy import array
        as_list = list(obj)
        try:
            return _array_type(as_list, array(as_list).dtype.name)
        except (ValueError, TypeError):
            # Ragged or mixed content -- fall back to the leading element's type
            return _array_type(as_list, None)
    if isinstance(obj, generic):
        obj = obj.item()
    if obj is None:
        return 'string', 'None'
    if isinstance(obj, bool):
        # numpy would call this 'bool'; the filewriter wants an explicit width
        return 'int64', int(obj)

    name = np_dtype(type(obj)).name
    if name == 'object':
        raise RuntimeError(f'Unrecognised type {type(obj)} for {obj!r}')
    return _DTYPE_ALIASES.get(name, name), obj


def _array_type(values: list, dtype_name: str | None) -> tuple[str, Any]:
    if dtype_name in (None, 'object'):
        element = values
        while isinstance(element, (list, tuple)) and len(element):
            element = element[0]
        from numpy import dtype as np_dtype
        dtype_name = np_dtype(type(element)).name if not isinstance(element, list) else 'double'
    dtype = _DTYPE_ALIASES.get(dtype_name, dtype_name)
    return dtype, _cast_elements(values, dtype)


def _cast_elements(values, dtype: str):
    """Make every element match the array's declared dtype.

    An exact-integer expression yields a Python ``int``; leaving it inside an array
    declared ``double`` gives a reader mixed types under a single dtype.
    """
    if dtype == 'double':
        cast = float
    elif dtype.startswith('int') or dtype.startswith('uint'):
        cast = int
    else:
        return values

    def apply(value):
        if isinstance(value, (list, tuple)):
            return [apply(item) for item in value]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return value
        return cast(value)

    return apply(values)


def to_absolute(parent: str, path: str) -> str:
    """Rewrite a relative ``depends_on`` target against its parent group path."""
    if path == '.':
        return '.'
    return f'{parent}/{path}'


def absolutize_depends_on(node: dict, parent_path: str) -> dict:
    """Recursively rewrite relative ``depends_on`` values to absolute paths.

    ``parent_path`` is the NeXus path of ``node``'s parent group.
    """
    name = node_name(node)
    path = f'{parent_path}/{name}' if name else parent_path

    if is_dataset(node) and node['config'].get('name') == 'depends_on':
        value = node['config'].get('values')
        if isinstance(value, str) and not value.startswith('/'):
            node['config']['values'] = to_absolute(parent_path, value)

    for attr in (node.get('attributes') or []):
        if attr.get('name') == 'depends_on':
            value = attr.get('values')
            if isinstance(value, str) and not value.startswith('/'):
                attr['values'] = to_absolute(parent_path, value)

    for child in children_of(node):
        if isinstance(child, dict):
            absolutize_depends_on(child, path if is_group(node) else parent_path)

    return node
