from __future__ import annotations

from dataclasses import dataclass

from mccode_antlr.assembler import Assembler
from scipp import Variable
from .component import Component


@dataclass
class Guide(Component):
    length: Variable
    left: float | tuple[float]  # m-value for x > 0 face
    right: float | tuple[float] # m-value for x < 0 face
    top: float | tuple[float]  # m-value for y > 0 face
    bottom: float | tuple[float]   # m-value for the y < 0 face


@dataclass
class StraightGuide(Guide):
    width: Variable
    height: Variable

    @classmethod
    def from_calibration(cls, cal: dict):
        from scipp import vector as v
        from scipp.spatial import rotations_from_rotvecs as r
        name = cal['name']
        position = cal.get('position', v([0, 0, 0.], unit='m'))
        orientation = cal.get('orientation', r(v([0, 0, 0.], unit='deg')))
        length = cal['length']
        m = cal.get('m', 1.0)
        left = cal.get('left', m)
        right = cal.get('right', m)
        top = cal.get('top', m)
        bottom = cal.get('bottom', m)
        if any(isinstance(x, tuple) for x in (left, right, top, bottom)):
            raise ValueError('StraightGuide does not support tuple m values')
        width = cal['width']
        height = cal['height']
        return cls(name, position, orientation, length, left, right, top, bottom, width, height)

    def __mccode__(self) -> tuple[str, dict]:
        p = {
            'w1': self.width.to(unit='m').value,
            'h1': self.height.to(unit='m').value,
            'l': self.length.to(unit='m').value,
            'mleft': self.left,
            'mright': self.right,
            'mtop': self.top,
            'mbottom': self.bottom,
            'R0': 0.99,
            'Qc': 0.0217,
            'alpha': 3.1,
            'W': 0.003,
            'G': -9.82
        }
        p['w2'] = p['w1']
        p['h2'] = p['h1']
        return 'Guide_gravity', p


@dataclass
class StraightGuides:
    name: str
    segments: list[StraightGuide]

    @classmethod
    def from_calibration(cls, cal: dict[str, dict | str]):
        """Convert a dictionary of dictionaries to a list of StraightGuides

        This is likely called from Section.from_calibration, which would insert
        the *Section* name as an entry in the dictionary. This is the list's parent
        which we can store separately.
        """
        parent = cal.pop('name')
        segments = []
        for name, cdict in cal.items():
            if not isinstance(cdict, dict):
                raise ValueError("Only dicts should be in this calibration dictionary")
            if 'name' not in cdict:
                cdict['name'] = name
            segments.append(StraightGuide.from_calibration(cdict))
        return cls(parent, segments)

    def to_mccode(self, assembler: Assembler):
        for segment in self.segments:
            segment.to_mccode(assembler)


@dataclass
class TaperedGuide(Guide):
    in_width: Variable
    in_height: Variable
    out_width: Variable
    out_height: Variable

    @classmethod
    def from_calibration(cls, cal: dict):
        from scipp import vector as v
        from scipp.spatial import rotations_from_rotvecs as r
        name = cal['name']
        position = cal.get('position', v([0, 0, 0.], unit='m'))
        orientation = cal.get('orientation', r(v([0, 0, 0.], unit='deg')))
        length = cal['length']
        m = cal.get('m', 1.0)
        left = cal.get('left', m)
        right = cal.get('right', m)
        top = cal.get('top', m)
        bottom = cal.get('bottom', m)
        if any(isinstance(x, tuple) for x in (left, right, top, bottom)):
            raise ValueError('StraightGuide does not support tuple m values')
        in_width = cal.get('in_width', cal.get('width'))
        out_width = cal.get('out_width', cal.get('width'))
        in_height = cal.get('in_height', cal.get('height'))
        out_height = cal.get('out_height', cal.get('height'))
        return cls(name, position, orientation, length, left, right, top, bottom,
                   in_width, out_width, in_height, out_height)

    def __mccode__(self) -> tuple[str, dict]:
        p = {
            'w1': self.in_width.to(unit='m').value,
            'w2': self.out_width.to(unit='m').value,
            'h1': self.in_height.to(unit='m').value,
            'h2': self.out_height.to(unit='m').value,
            'l': self.length.to(unit='m').value,
            'mleft': self.left,
            'mright': self.right,
            'mtop': self.top,
            'mbottom': self.bottom,
            'R0': 0.99,
            'Qc': 0.0217,
            'alpha': 3.1,
            'W': 0.003,
            'G': -9.82
        }
        return 'Guide_gravity', p


@dataclass
class TaperedGuides:
    name: str
    segments: list[TaperedGuide]

    @classmethod
    def from_calibration(cls, cal: dict[str, dict | str]):
        parent = cal.pop('name')
        segments = []
        for name, cdict in cal.items():
            if 'name' not in cdict:
                cdict['name'] = name
            segments.append(TaperedGuide.from_calibration(cdict))
        return cls(parent, segments)

    def to_mccode(self, assembler: Assembler):
        for segment in self.segments:
            segment.to_mccode(assembler)


@dataclass
class PartialEllipse:
    major: Variable
    minor: Variable
    offset: Variable

    @classmethod
    def from_calibration(cls, length: Variable, cal: dict):
        from scipp import sqrt
        if not all(x in cal for x in ('major', 'minor', 'offset')):
            # calculate the ellipse parameters from the provided information
            all_of = 'in', 'out'
            any_of = 'entry', 'exit', 'midpoint'
            if not (all(x in cal for x in all_of) and any(x in cal for x in any_of)):
                raise ValueError()
            i = cal['in']  # distance from focal point to start of guide
            o = cal['out']  # distance from end of guide to other focal point
            foci = i + length + o
            if 'midpoint' in cal:
                w = cal['midpoint']
                cal['major'] = sqrt(foci * foci  + w * w) / 2
                cal['minor'] = w / 2
            else:
                entry = 'entry' in cal
                w, t, b = (cal['entry'], o, i) if entry else (cal['exit'], i ,o)
                t += length
                b = sqrt(b * b + w * w / 4) + sqrt(t * t + w * w / 4)
                cal['major'] = b / 2
                cal['minor'] = sqrt(b * b - foci * foci) / 2
            cal['offset'] = foci / 2 - i
        major = cal['major']
        minor = cal['minor']
        offset = cal['offset']
        return cls(major, minor, offset)

    def mccode_pars(self, post):
        p = {
            f'majorAxis{post}': self.major.to(unit='m').value,
            f'minorAxis{post}': self.minor.to(unit='m').value,
            f'majorAxisoffset{post}': self.offset.to(unit='m').value,
        }
        return p


@dataclass
class EllipticGuide(Guide):
    horizontal: PartialEllipse
    vertical:  PartialEllipse

    @classmethod
    def from_calibration(cls, cal: dict):
        from scipp import sum, vector as v
        from scipp.spatial import rotations_from_rotvecs as r
        name = cal['name']
        position = cal.get('position', v([0, 0, 0.], unit='m'))
        orientation = cal.get('orientation', r(v([0, 0, 0.], unit='deg')))
        length = cal['length']
        m = cal.get('m', 1.0)
        left = cal.get('left', m)
        right = cal.get('right', m)
        top = cal.get('top', m)
        bottom = cal.get('bottom', m)

        ms = left, right, top, bottom
        if any(isinstance(x, tuple) for x in ms):
            if not all(isinstance(x, tuple) for x in ms):
                raise ValueError('All m values should be scalars or tuples')
            count = len(left)
            if not all(len(x) == count for x in ms):
                raise ValueError('Tuple m values must be the same length')
            if not length.size == count:
                raise ValueError('Segment lengths and m values must be the same length')
            gl = sum(length)
        else:
            gl = length

        horizontal = PartialEllipse.from_calibration(gl, cal.get('horizontal'))
        vertical = PartialEllipse.from_calibration(gl, cal.get('vertical'))

        return cls(name, position, orientation, length, left, right, top, bottom, horizontal, vertical)

    def __mccode__(self) -> tuple[str, dict]:
        from scipp import sum
        p = dict()
        if isinstance(self.left, tuple):
            p['l'] = sum(self.length).to(unit='m').value
            p['nSegments'] = len(self.left)
            p['seglength'] = f'{self.name}_lens'
            for n in ('right', 'left', 'top', 'bottom'):
                p[f'mvalues{n}'] = f'{self.name}_{n}'
        else:
            p['l'] = self.length.to(unit='m').value
            for n in ('left', 'right', 'top', 'bottom'):
                p[f'm{n}'] = getattr(self, n)
        p.update(self.horizontal.mccode_pars('xw'))
        p.update(self.vertical.mccode_pars('yh'))

        return 'Elliptic_guide_gravity', p

    def to_mccode(self, assembler: Assembler):
        if isinstance(self.left, tuple):
            assembler.declare_array('double', f'{self.name}_lens', self.length.to(unit='m').values)
            for n in ('left', 'right', 'top', 'bottom'):
                assembler.declare_array('double', f'{self.name}_{n}', getattr(self, n))
        super().to_mccode(assembler)
