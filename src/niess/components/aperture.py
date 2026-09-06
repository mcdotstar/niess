from scipp import Variable
from mccode_antlr.assembler import Assembler
from mccode_antlr.instr import Instance
from mccode_antlr.common import InstrumentParameter
from .component import Component


class Aperture(Component):
    width: Variable
    height: Variable
    #: EPICS PV root per driven edge, keyed as `edge_strings` keys it: 'left', 'right',
    #: 'bottom', 'top'. Inert unless the file is being written for a real run, so an
    #: instrument that declares them still emits the same McStas it always did.
    pv_roots: dict[str, str] | None = None

    @classmethod
    def from_calibration(cls, cal: dict):
        name = cal['name']
        position = cal['position']
        orientation = cal['orientation']
        width = cal['width']
        height = cal['height']
        return cls(
            name=name,
            position=position,
            orientation=orientation,
            width=width,
            height=height,
            pv_roots=cal.get('pv_roots'),
        )

    def __niess_pv_root__(self, key: str) -> str | None:
        """The positioner driving one edge, keyed the way `edge_strings` keys them."""
        return (self.pv_roots or {}).get(key)

    def edge_strings(self) -> dict[str, str]:
        # the base Aperture has a fixed size, eventually emitted as OFF geometry
        return {}

    def edge_parameters(self) -> dict[str, InstrumentParameter]:
        """The run-time knobs its edges are set by, keyed by which edge."""
        return {k: InstrumentParameter.parse(v) for k, v in self.edge_strings().items()}

    # def __mccode_extra__(self) -> dict[str, float]:
    #     return {
    #         'width': self.width.to(unit='m').value,
    #         'height': self.height.to(unit='m').value,
    #     }

    def __mccode__(self):
        edges = self.edge_parameters()
        params = {}
        if all(x in edges for x in ('left', 'right')):
            params['xmin'] = edges['left'].name
            params['xmax'] = edges['right'].name
        else:
            params['xwidth'] = self.width.to(unit='m', dtype='float').value
        if all(y in edges for y in ('bottom', 'top')):
            params['ymin'] = edges['bottom'].name
            params['ymax'] = edges['top'].name
        else:
            params['yheight'] = self.height.to(unit='m', dtype='float').value
        return 'Slit', params

    def to_mccode(
            self, assembler: Assembler,
            at: Instance | str | None = None, rotate: Instance | str | None = None,
            insert_provenance_metadata: bool = True,
    ):
        from ..assembler import ensure_runtime_parameter as ensure
        for parameter in self.edge_parameters().values():
            ensure(assembler, parameter)
        return super().to_mccode(assembler, at, rotate, insert_provenance_metadata=insert_provenance_metadata)



class Jaw(Aperture):
    """A special variable width aperture, open by default and configured at runtime"""

    def edge_strings(self) -> dict[str, str]:
        half = self.width.to(dtype='float', unit='m').value / 2.0
        return {'left': f'{self.name}_l/"m" = {-half}', 'right': f'{self.name}_r/"m" = {half}',}


class Slit(Aperture):
    """A special variable aperture, open by default and configured at runtime"""

    def edge_strings(self) -> dict[str, str]:
        w = self.width.to(unit='m', dtype='float').value / 2.0
        h = self.height.to(unit='m', dtype='float').value / 2.0
        return {
            'left': f'{self.name}_l/"m" = {-w}',
            'right': f'{self.name}_r/"m" = {w}',
            'bottom': f'{self.name}_b/"m" = {-h}',
            'top': f'{self.name}_t/"m" = {h}',
        }
