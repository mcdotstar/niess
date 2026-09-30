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

    def _edge_knobs(self, **half) -> dict[str, str]:
        """Driven edges, as ESS names and publishes them.

        Each knob is ``{name}_{edge}``, named for the positioner the edge is published
        as (``sample_jaws.left.value``), and in millimetres, as ESS publishes a jaw.
        The conversion to metres happens where the knob is inserted into the McStas
        component -- see `__mccode__`.
        """
        signs = {'left': -1, 'right': 1, 'bottom': -1, 'top': 1}
        return {edge: f'{self.name}_{edge}/"mm" = {signs[edge] * size}'
                for edge, size in half.items()}

    def _half(self, dimension: Variable) -> float:
        """Half of a dimension, in the edge knobs' unit."""
        return dimension.to(unit='mm', dtype='float').value / 2.0

    def __mccode__(self):
        from .motor import unquote
        edges = self.edge_parameters()

        def metres(edge):
            knob = edges[edge]
            factor = {'mm': 0.001, 'm': None}[unquote(knob.unit)]
            return knob.name if factor is None else f'{factor} * {knob.name}'

        params = {}
        if all(x in edges for x in ('left', 'right')):
            params['xmin'] = metres('left')
            params['xmax'] = metres('right')
        else:
            params['xwidth'] = self.width.to(unit='m', dtype='float').value
        if all(y in edges for y in ('bottom', 'top')):
            params['ymin'] = metres('bottom')
            params['ymax'] = metres('top')
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
        w = self._half(self.width)
        return self._edge_knobs(left=w, right=w)


class Slit(Aperture):
    """A special variable aperture, open by default and configured at runtime"""

    def edge_strings(self) -> dict[str, str]:
        w, h = self._half(self.width), self._half(self.height)
        return self._edge_knobs(left=w, right=w, bottom=h, top=h)
