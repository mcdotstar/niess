from dataclasses import dataclass
from scipp import Variable
from mccode_antlr.assembler import Assembler
from .component import Component

@dataclass
class Aperture(Component):
    width: Variable
    height: Variable

    @classmethod
    def from_calibration(cls, cal: dict):
        name = cal['name']
        position = cal['position']
        orientation = cal['orientation']
        width = cal['width']
        height = cal['height']
        return cls(name, position, orientation, width, height)


@dataclass
class Jaw(Aperture):
    """A special variable width aperture, open by default and configured at runtime"""

    def __mccode__(self) -> tuple[str, dict]:
        params = {
            'xmin': f'{self.name}_l',
            'xmax': f'{self.name}_r',
            'yheight': self.height.to(unit='m').value,
        }
        return 'Slit', params

    def to_mccode(self, assembler: Assembler):
        from ..mccode import ensure_runtime_line as ensure
        half = self.width.to(unit='m').value / 2
        ensure(assembler, f'{self.name}_l/"m" = {-half}')
        ensure(assembler, f'{self.name}_r/"m" = {half}')
        return super().to_mccode(assembler)


@dataclass
class Slit(Aperture):
    """A special variable aperture, open by default and configured at runtime"""

    def __mccode__(self) -> tuple[str, dict]:
        params = {
            'xmin': f'{self.name}_l',
            'xmax': f'{self.name}_r',
            'ymin': f'{self.name}_b',
            'ymax': f'{self.name}_t',
        }
        return 'Slit', params

    def to_mccode(self, assembler: Assembler):
        from ..mccode import ensure_runtime_line as ensure
        half = self.width.to(unit='m').value / 2
        ensure(assembler, f'{self.name}_l/"m" = {-half}')
        ensure(assembler, f'{self.name}_r/"m" = {half}')
        half = self.height.to(unit='m').value / 2
        ensure(assembler, f'{self.name}_b/"m" = {-half}')
        ensure(assembler, f'{self.name}_t/"m" = {half}')
        return super().to_mccode(assembler)
