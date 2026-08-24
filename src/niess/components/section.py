# from dataclasses import dataclass, fields
from __future__ import annotations

import msgspec
from networkx import DiGraph
from msgspec.structs import fields
from functools import lru_cache
from mccode_antlr.assembler import Assembler
from ..utilities import calibration


class Section(msgspec.Struct, tag=True):

    @classmethod
    def _component_fields(cls):
        """The fields which are components of this Section.

        Underscore-prefixed fields are per-class extras -- ``_flat`` controls how the
        section inserts itself into an Assembler, and a subclass may add others -- so
        they are deliberately invisible to every introspection method here. Filtering
        in one place keeps the name, type and item views consistent with each other
        however many there are, and wherever they are declared.

        The same rule applies to a Base, so it lives in :mod:`niess.tree` and this
        defers to it -- Section is not a Base, and the two would otherwise drift.
        """
        from ..tree import component_fields
        return component_fields(cls)

    def __niess_children__(self):
        """This section's components, in declaration order -- which is beam order."""
        from ..tree import default_children
        return default_children(self)

    @classmethod
    @lru_cache(maxsize=None)
    def parts(cls):
        """Get the ordered list of components which make up this Section"""
        return [fi.name for fi in cls._component_fields()]

    @classmethod
    @lru_cache(maxsize=None)
    def types(cls):
        """Get the ordered list of component types which make up this Section"""
        return [fi.type for fi in cls._component_fields()]

    @classmethod
    @lru_cache(maxsize=None)
    def items(cls):
        """Get the ordered list of component names and types which make up this Section"""
        return [(n, t) for n, t in zip(cls.parts(), cls.types())]

    @classmethod
    @lru_cache(maxsize=None)
    def field_types(cls):
        return {fi.name: fi.type for fi in cls._component_fields()}

    def to_mccode_flat(self, assembler: Assembler, *args, **kwargs):
        """
        Add this section of components directly into the provided assembler's Instr.
        """
        for part in self.parts():
            getattr(self, part).to_mccode(assembler, *args, **kwargs)

    def to_mccode_nested(self, assembler: Assembler, *args, **kwargs):
        """
        Convert this section of components into a McStas Instr via a provided assembler.
        Inserting it into the Instr hierarchy as if an %included separate .instr file.
        """
        import re
        name = re.sub('([A-Z]+)', r'_\1', type(self).__name__).lower()
        with assembler.included(f"{assembler.name}{name}") as section:
            self.to_mccode_flat(section, *args, **kwargs)

    def to_mccode(self, *args, **kwargs):
        if hasattr(self, '_flat') and getattr(self, '_flat', False):
            self.to_mccode_flat(*args, **kwargs)
        else:
            self.to_mccode_nested(*args, **kwargs)

    @classmethod
    @calibration
    def from_calibration(cls, parameters: dict):
        for part in cls.parts():
            assert part in parameters, f"{part} is not present in the parameters"

        def named_par(name):
            if 'name' not in parameters[name]:
                parameters[name]['name'] = name
            return parameters[name]

        def to_type(name):
            typ = cls.field_types()[name]
            if isinstance(parameters[name], typ):
                return parameters[name]
            return typ.from_calibration(named_par(name))

        return cls(*[to_type(n) for n in cls.parts()])

    def to_dict(self):
        return {f: getattr(self, f) for f in self.parts()}

    @classmethod
    def from_dict(cls, d):
        # TODO make a function to recurse through a dictionary and ensure
        #      scipp.Variable and mccode_antlr.? are converted
        return cls.from_calibration(d)

    def to_graph(self):
        from networkx import DiGraph
        graph = DiGraph()
        self.add_to_graph(None, '', graph)
        return graph

    def add_to_graph(self, upstream: str | None, unused_section_name: str, graph: DiGraph):
        last = upstream
        for name in self.__struct_fields__:
            names = getattr(self, name).add_to_graph(last, name, graph)
            if isinstance(names, list) and len(names) == 1:
                last = names[0]
        return [last]