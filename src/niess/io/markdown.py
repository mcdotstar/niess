import msgspec
from typing import Callable

class MarkdownRow(msgspec.Struct):
    contents: tuple[list[str], ...]
    lengths: tuple[int, ...]
    is_heading: bool = False

    def row_lengths(self):
        def max_or_zero(col):
            if col is None or len(col) == 0:
                return 0
            return max(len(c) for c in col)

        return [max_or_zero(col) for col in self.contents]

    def __post_init__(self):
        def correct(content):
            if isinstance(content, str):
                return content.split('\n')
            return content
        self.contents = tuple(correct(c) for c in self.contents)
        self.lengths = tuple(self.row_lengths())

    @classmethod
    def from_json(cls, data, headings: list[str], transforms: dict[str,Callable]):
        if isinstance(data, (str, bytes)):
            from json import loads
            data = loads(data)
        contents = [transforms[heading](data[heading]) for heading in headings]
        lengths = [0 for _ in headings]
        return cls(tuple(contents), tuple(lengths))

    def __str__(self):
        rep = ''
        height = 1 + max(len(content) for content in self.contents)
        # Top line (if heading)
        if self.is_heading:
            for length in self.lengths:
                rep += '+' + '-' * (length + 2)
            rep += '+\n'
        # Contents line(s)
        for line in range(height):
            for col, length in zip(self.contents, self.lengths):
                if len(col) > line:
                    rep += f'| {col[line]:{length}} '
                else:
                    rep += '|' + ' ' * (length + 2)
            rep += '|\n'
        # Bottom line
        for length in self.lengths:
            rep += '+' + ('=' if self.is_heading else '-') * (length + 2)
        rep += '+\n'
        return rep

class MarkdownTable(msgspec.Struct):
    title: str
    rows: list[MarkdownRow]

    def __post_init__(self):
        self.rows[0].is_heading = True
        lengths = self.rows[0].lengths
        for row in self.rows[1:]:
            lengths = [max(a, b) for a, b in zip(lengths, row.lengths)]
        for row in self.rows:
            row.lengths = tuple(lengths)

    def __str__(self):
        return ''.join(str(row) for row in self.rows)


def to_str(value):
    if hasattr(value, '__len__') and isinstance(value[0], float):
        return '(' + ','.join(f'{x:0.3f}' for x in value) + ')'
    return str(value)

def scipp_variable_transform(x):
    if not isinstance(x, dict) or 'obj' not in x:
        raise ValueError(f'{x} is not a scipp variable?')
    o = x['obj']
    value = o.get('value', o.get('values', None))
    unit = o.get('unit')
    dims = o.get('dims')
    ret = to_str(value)
    if unit is not None and unit != 'dimensionless':
        ret += f' {unit}'
    if dims is not None:
        ret += f' {dims}'
    return ret


def parameter_one(d, depth):
    if isinstance(d, dict) and 'name' in d and 'scipp.Variable' == d['name']:
        return scipp_variable_transform(d)
    elif isinstance(d, dict):
        return '\n' + '\n'.join(parameter_dict(d, depth+1))
    return str(d)


def parameter_dict(d, depth=0):
    return ['  '*depth + f'- {k} = {parameter_one(v, depth)}' for k, v in d.items()]


def parameters_transform(parameters):
    return '\n'.join(parameter_dict(parameters))


def to_markdown(obj):
    from json import loads
    from .json import to_json
    data = loads(to_json(obj))

    if not 'name' in data or not 'obj' in data:
        raise TypeError('Missing "name" and "obj" fields')

    title = data['name']
    data = data['obj']

    # Data is now an (ordered) dictionary, with keys equal to component names
    headings = ['name', 'position', 'orientation', 'parameters']
    transformations = {
        'name': lambda x: f'`{x}`',
        'position': scipp_variable_transform,
        'orientation': scipp_variable_transform,
        'parameters': parameters_transform,
    }

    def one_entry(entry):
        name, pos, ori = entry.pop('name'), entry.pop('position'), entry.pop('orientation')
        entry = dict(name=name, position=pos, orientation=ori, parameters=entry)
        return MarkdownRow.from_json(entry, headings, transformations)

    def one_component(component):
        ret = []
        if 'segments' in component:
            for segment in component['segments']:
                ret.append(one_entry(segment))
        else:
            ret.append(one_entry(component))
        return ret

    rows = [r for value in data.values() for r in one_component(value)]
    row0 = MarkdownRow(headings, headings)
    table = MarkdownTable(title, [row0] + rows)
    return table