from scipp import Variable
from mccode_antlr.assembler import Assembler
from mccode_antlr.instr import Instance
from .component import Component


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
        return cls(
            name=name,
            position=position,
            orientation=orientation,
            width=width,
            height=height
        )

    def __mccode_extra__(self) -> dict[str, float]:
        return {
            'width': self.width.to(unit='m').value,
            'height': self.height.to(unit='m').value,
        }


class Jaw(Aperture):
    """A special variable width aperture, open by default and configured at runtime"""

    def edge_parameters(self) -> dict[str, str]:
        """The run-time knobs its edges are set by, keyed by which edge.

        Named here rather than spelled out in both the emitted parameters and the
        declarations that create them -- and now also read by a NeXus file, which links
        each edge to the NXlog carrying its value rather than writing down a number that
        a run is free to change.
        """
        return {'left': f'{self.name}_l', 'right': f'{self.name}_r'}

    def __mccode__(self) -> tuple[str, dict]:
        edges = self.edge_parameters()
        params = {
            'xmin': edges['left'],
            'xmax': edges['right'],
            'yheight': self.height.to(unit='m').value,
        }
        return 'Slit', params

    def to_mccode(
            self, assembler: Assembler,
            at: Instance | str | None = None, rotate: Instance | str | None = None,
            insert_provenance_metadata: bool = True,
    ):
        from ..mccode import ensure_runtime_line as ensure
        edges = self.edge_parameters()
        half = self.width.to(unit='m').value / 2
        ensure(assembler, f'{edges["left"]}/"m" = {-half}')
        ensure(assembler, f'{edges["right"]}/"m" = {half}')
        return super().to_mccode(assembler, at, rotate, insert_provenance_metadata=insert_provenance_metadata)


class Slit(Aperture):
    """A special variable aperture, open by default and configured at runtime"""

    def edge_parameters(self) -> dict[str, str]:
        """The run-time knobs its four edges are set by, keyed by which edge."""
        return {'left': f'{self.name}_l', 'right': f'{self.name}_r',
                'bottom': f'{self.name}_b', 'top': f'{self.name}_t'}

    def __mccode__(self) -> tuple[str, dict]:
        edges = self.edge_parameters()
        params = {
            'xmin': edges['left'],
            'xmax': edges['right'],
            'ymin': edges['bottom'],
            'ymax': edges['top'],
        }
        return 'Slit', params

    def to_mccode(
            self, assembler: Assembler,
            at: Instance | str | None = None, rotate: Instance | str | None = None,
            insert_provenance_metadata: bool = True,
    ):
        from ..mccode import ensure_runtime_line as ensure
        edges = self.edge_parameters()
        half = self.width.to(unit='m').value / 2
        ensure(assembler, f'{edges["left"]}/"m" = {-half}')
        ensure(assembler, f'{edges["right"]}/"m" = {half}')
        half = self.height.to(unit='m').value / 2
        ensure(assembler, f'{edges["bottom"]}/"m" = {-half}')
        ensure(assembler, f'{edges["top"]}/"m" = {half}')
        return super().to_mccode(assembler, at, rotate, insert_provenance_metadata=insert_provenance_metadata)
