"""Walk an assembled instrument and emit its NeXus Structure JSON.

The walk operates on ``mccode_antlr``'s ``Instr``/``Instance`` tree -- the output of
``Assembler`` -- exactly as :mod:`niess.brep` does, so niess composites that
hand-build several McCode components have already dissolved into flat instances by
the time anything here runs.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from ...dispatch import component_type_category, component_type_name, expr_float
from ...provenance import NiessProvenance
from ...spatial import mccode_angles_without_turn
from . import expression
from ..nodes import (
    absolutize_depends_on,
    add_attribute,
    dataset,
    get_attribute,
    group,
    node_name,
)
from .orientation import NXOrient, NXParts
from .registry import DEFAULT_NEXUS_REGISTRY
from .variables import declared_variables

logger = logging.getLogger(__name__)

DEFAULT_NXLOG_ROOT = '/entry/parameters'
INSTRUMENT_PATH = '/entry/instrument'

COMPONENT_GROUP_TO_NEXUS = {'Guide': 'NXguide', 'Collimator': 'NXcollimator'}
COMPONENT_CATEGORY_TO_NEXUS = {'sources': 'NXmoderator', 'monitors': 'NXdetector'}
COMPONENT_TYPE_NAME_TO_NEXUS = {
    'Arm': 'NXcoordinate_system',
    'DiskChopper': 'NXdisk_chopper',
    'FermiChopper': 'NXfermi_chopper',
    'FermiChopper_ILL': 'NXfermi_chopper',
    'Fermi_chop2a': 'NXfermi_chopper',
    'Filter_gen': 'NXfilter',
    'Filter_graphite': 'NXfilter',
    'Elliptic_guide_gravity': 'NXguide',
    # The ESS moderator, emitted by niess.components.source.ESSource for any
    # instrument. McCode files it under the 'mcstas-comps' category rather than
    # 'sources', so the category fallback below never catches it.
    'ESS_butterfly': 'NXmoderator',
    'Mirror': 'NXmirror',
    'Monochromator_flat': 'NXmonochromator',
    'Monochromator_curved': 'NXmonochromator',
    'Monochromator_pol': 'NXpolarizer',
    'Pol_SF_ideal': 'NXflipper',
    'Pol_bender': 'NXpolarizer',
    'Pol_mirror': 'NXpolarizer',
    'SNS_source': 'NXmoderator',
    'SNS_source_analytic': 'NXmoderator',
    'Source_pulsed': 'NXmoderator',
    'Selector': 'NXvelocity_selector',
    'V_selector': 'NXvelocity_selector',
    'ViewModISIS': 'NXmoderator',
}


# Parameters the fallback translation can fill in for a few NeXus classes, keyed by
# the NeXus name and valued by the McCode parameter it comes from. Ported from
# moreniius' NEXUS_TO_COMPONENT, which listed four classes but only ever populated
# this one -- the other three mapped to empty dictionaries.
NEXUS_CLASS_PARAMETERS = {
    'NXfermi_chopper': {
        'rotation_speed': 'nu',
        'radius': 'radius',
        'slit': 'w',
        'r_slit': 'curvature',
        'number': 'nslit',
        'width': 'xwidth',
        'height': 'yheight',
    },
}


def _vector(values) -> 'Vector':
    """A McCode position from plain numbers; the struct's fields are expressions."""
    from mccode_antlr.common import Expr
    from mccode_antlr.instr.orientation import Vector
    return Vector(*(Expr.float(float(v)) for v in values))


def _angles(values) -> 'Angles':
    """McCode angles from plain numbers; the struct's fields are expressions."""
    from mccode_antlr.common import Expr
    from mccode_antlr.instr.orientation import Angles
    return Angles(*(Expr.float(float(v)) for v in values))


def component_body(
        nx_class: str,
        children: list | None = None,
        attrs: dict | None = None,
        name: str | None = None,
) -> dict:
    """What a translator returns: the class and contents of one component's group.

    ``name`` overrides the group's name, which defaults to the McStas instance's. Use
    it where the instance name is an artefact of how the instrument was built rather
    than something a reader of the file should see -- a composite emitted as several
    instances, say, whose NeXus group should carry the name of the thing itself.
    """
    return {
        'nx_class': nx_class,
        'children': list(children or []),
        'attrs': dict(attrs or {}),
        'name': name,
    }


@dataclass
class Translation:
    """Everything a translator needs about one component instance."""
    context: 'NexusContext'
    instance: Any
    index: int
    provenance: NiessProvenance | None = None

    def __post_init__(self):
        if self.provenance is None:
            self.provenance = NiessProvenance.from_instance(self.instance)

    @property
    def instr(self):
        """The whole instrument, for translators that must inspect sibling instances."""
        return self.context.instr

    @property
    def name(self) -> str:
        return self.instance.name

    @property
    def type_name(self) -> str:
        return component_type_name(self.instance)

    def defines(self, name: str) -> bool:
        return self.instance.defines_parameter(name)

    def resolve(self, name: str, default=None):
        """Resolve a named instance parameter to a literal or a link description."""
        parameter = self.instance.get_parameter(name)
        if parameter is None:
            logger.debug(f'{self.type_name} does not define the parameter {name}')
            return expression.Literal(default)
        return self.context.resolve(parameter.value)

    def parameter(self, name: str, default=None, dtype=None):
        """The literal value of a parameter, or ``default`` if it is not constant."""
        resolved = self.resolve(name, default=default)
        value = expression.literal_value(resolved, default)
        if dtype is not None and value is not None:
            try:
                return dtype(value)
            except (TypeError, ValueError):
                return default
        return value

    def parameter_node(
            self,
            name: str,
            source: str | None = None,
            dtype=None,
            attrs: dict | None = None,
    ):
        """A node for a parameter: dataset when constant, link group when not.

        ``dtype`` coerces a constant value only -- a runtime-linked parameter has
        no value here to coerce.
        """
        resolved = self.resolve(source or name)
        if dtype is not None and isinstance(resolved, expression.Literal):
            try:
                resolved = expression.Literal(dtype(resolved.value))
            except (TypeError, ValueError):
                pass
        return expression.parameter_node(name, resolved, attrs=attrs)

    def siblings_in_group(self) -> list:
        """Instances sharing this one's ``disc_group_id`` provenance tag, in order."""
        if self.provenance is None:
            return []
        group_id = self.provenance.extra.get('disc_group_id')
        if group_id is None:
            return []

        found = []
        for instance in self.instr.components:
            other = NiessProvenance.from_instance(instance)
            if other is not None and other.extra.get('disc_group_id') == group_id:
                found.append((other.extra.get('disc_group_index', 0), instance))
        return [instance for _, instance in sorted(found, key=lambda pair: pair[0])]


@dataclass
class NexusContext:
    """Instrument-level state shared by every translator."""
    instr: Any
    nxlog_root: str = DEFAULT_NXLOG_ROOT
    origin_name: str | None = None
    registry: Any = None
    declared: dict = field(default_factory=dict)
    orientations: dict = field(default_factory=dict)
    origin: Any = None
    nodes: dict = field(default_factory=dict)
    suppressed: set = field(default_factory=set)
    graph: Any = None

    def __post_init__(self):
        from mccode_antlr.instr.orientation import Orient

        if self.registry is None:
            self.registry = DEFAULT_NEXUS_REGISTRY
        if not self.declared:
            self.declared = declared_variables(self.instr)
        if not self.orientations:
            self.orientations = self.instr.resolve_orientations()
        if self.graph is None:
            self.graph = self._build_graph()
        if self.origin is None:
            self.origin = self._find_origin() or Orient()

    def _build_graph(self):
        from networkx import DiGraph

        graph = DiGraph()
        names = [instance.name for instance in self.instr.components]
        graph.add_nodes_from(names)
        # McCode instruments are linear unless something says otherwise
        graph.add_edges_from([(names[i], names[i + 1]) for i in range(len(names) - 1)])
        return graph

    def _find_origin(self):
        if self.origin_name is not None:
            candidates = [c for c in self.instr.components if c.name == self.origin_name]
            if not candidates:
                logger.warning(
                    f'No component named {self.origin_name}; using ABSOLUTE positions'
                )
                return None
            if len(candidates) > 1:
                logger.error(f'{len(candidates)} components named {self.origin_name}; using the first')
        else:
            candidates = [c for c in self.instr.components
                          if component_type_category(c) == 'samples']
            if not candidates:
                logger.warning('No "sample" category component; using ABSOLUTE positions')
                return None
            if len(candidates) > 1:
                logger.warning(
                    f'More than one "sample" category component; using {candidates[0].name} as origin'
                )
        self.origin_name = candidates[0].name
        return self.orientations[candidates[0].name]

    def resolve(self, expr):
        return expression.resolve(expr, self.declared, self.instr.parameters, self.nxlog_root)

    def literal(self, value):
        """Reduce a value -- or an iterable of them -- to plain JSON-able data.

        Used for attribute values such as transformation vectors, which have no
        node of their own to carry a link and so must fold to constants.
        """
        from mccode_antlr.common import Expr

        if isinstance(value, Expr):
            resolved = self.resolve(value)
            return expression.literal_value(resolved, str(value))
        if isinstance(value, str):
            return value
        if hasattr(value, '__iter__'):
            return [self.literal(item) for item in value]
        return value

    def inputs(self, name) -> list:
        return list(self.graph.reverse(copy=False)[name])

    def outputs(self, name) -> list:
        return list(self.graph[name])

    # -- transformation chain -------------------------------------------------

    def resolve_target(self, rel) -> str | None:
        """The absolute path a relative placement should depend on."""
        node = self.nodes.get(rel.name)
        if node is None:
            raise RuntimeError(f'transformations for {rel.name} defined out of order')
        # The path uses the name the group was *written* under, which a translator may
        # have overridden; self.nodes stays keyed by the McStas instance name, because
        # that is what a placement refers to.
        target = f'{INSTRUMENT_PATH}/{node_name(node)}' 
        if rel.name in self.suppressed:
            # The chain still resolves, but nothing will be written at that path
            logger.warning(
                f'{rel.name} is placed relative to a suppressed component; the emitted '
                'depends_on path will not exist in the written file'
            )

        depends_on = None
        for child in node.get('children') or []:
            if node_name(child) == 'depends_on' and child.get('module') == 'dataset':
                depends_on = child['config'].get('values')
                break
        if depends_on is None:
            return None
        if depends_on.startswith('/'):
            return depends_on
        return None if depends_on == '.' else f'{target}/{depends_on}'

    def frame_rotation(self, instance):
        """The turn a component's emitted frame carries that the object's does not.

        ``None`` when there is none, which is everything but a disc chopper today.
        """
        provenance = NiessProvenance.from_instance(instance)
        if provenance is None:
            return None
        rotvec = provenance.extra.get('mccode_frame_rotation')
        if not rotvec or not any(abs(float(a)) > 0 for a in rotvec):
            return None
        return [float(a) for a in rotvec]

    def frame_offset(self, instance):
        """The displacement a component's emitted origin carries that the object's does not.

        ``None`` when there is none, which is everything but a disc chopper today.
        """
        provenance = NiessProvenance.from_instance(instance)
        if provenance is None:
            return None
        offset = provenance.extra.get('mccode_frame_offset')
        if not offset or not any(abs(float(v)) > 0 for v in offset):
            return None
        return [float(v) for v in offset]

    def transformations(self, instance) -> dict[str, dict]:
        from mccode_antlr.instr.orientation import Angles, Parts, Vector

        def last_ref(refs, default=None):
            return refs[-1][0] if refs else default

        at_vec, at_rel = instance.at_relative
        rot_vec, rot_rel = instance.rotate_relative
        at_vec = Vector(*at_vec) if isinstance(at_vec, tuple) else at_vec
        rot_vec = Angles(*rot_vec) if isinstance(rot_vec, tuple) else rot_vec

        # A component emitted turned relative to the object it describes says so in its
        # provenance; the file records the object, so the turn comes back out here. Only
        # this component's own rotation is corrected -- `self.orientations` keeps the
        # emitted values, because anything placed RELATIVE to this one was placed against
        # the emitted frame and has to resolve against it.
        turn = self.frame_rotation(instance)
        if turn is not None:
            rot_vec = _angles(mccode_angles_without_turn(
                [expr_float(a) for a in rot_vec], turn))
        # ...and the same for where it sits. The emitted AT is `position + offset`, a
        # plain sum in whatever frame the component was placed against, so subtracting
        # the same vector from the same quantity recovers the object's own position.
        shift = self.frame_offset(instance)
        if shift is not None:
            at_vec = _vector(expr_float(a) - b for a, b in zip(at_vec, shift))

        trans: list[tuple[str, dict]] = []
        if at_rel is None:
            resolved = self.orientations[instance.name] - self.origin
            orient = NXOrient(
                self, resolved,
                rotation=None if turn is None else Parts.from_at_rotated(
                    Vector(),
                    _angles(mccode_angles_without_turn(
                        [expr_float(a) for a in resolved.angles()], turn)),
                    True),
                position=None if shift is None else Parts.from_at_rotated(
                    _vector(expr_float(a) - b
                            for a, b in zip(resolved.position(), shift)),
                    Angles(), True),
            )
            if rot_rel is None:
                return orient.transformations(instance.name)
            trans.extend(orient.position_transformations(instance.name))
            relative = NXOrient(self, self.orientations[rot_rel.name] - self.origin)
            trans.extend(relative.rotation_transformations(rot_rel.name, last_ref(trans)))
            rotation = Parts(Parts.from_at_rotated(Vector(), rot_vec, True).stack()).reduce()
            trans.extend(
                NXParts(self, rotation, rotation)
                .rotation_transformations(instance.name, last_ref(trans))
            )
        else:
            target = self.resolve_target(at_rel)
            parts = NXParts(
                self,
                Parts.from_at_rotated(at_vec, Angles(), True),
                Parts.from_at_rotated(Vector(), rot_vec, True),
            )
            trans.extend(parts.position_transformations(instance.name, target))
            if at_rel != rot_rel:
                at_orient = NXOrient(self, self.orientations[at_rel.name] - self.origin)
                trans.extend(
                    at_orient.rotation_inverse_transformations(instance.name, last_ref(trans, target))
                )
                if rot_rel is not None:
                    target = self.resolve_target(rot_rel)
                    rot_orient = NXOrient(self, self.orientations[rot_rel.name] - self.origin)
                    trans.extend(
                        rot_orient.rotation_transformations(rot_rel.name, last_ref(trans, target))
                    )
            trans.extend(parts.rotation_transformations(instance.name, last_ref(trans, target)))
            if not trans and target is not None:
                trans = [(target, None)]

        return dict(trans)


def outer_transform_dependency(transformations: dict[str, dict]) -> str:
    """The name of the most-dependent transformation in a singular chain."""
    names = list(transformations)
    if len(names) == 1:
        return names[0]

    depends = {}
    for name in names:
        value = get_attribute(transformations[name], 'depends_on')
        if value is None:
            raise ValueError(f'{name} in {names} is missing a "depends_on" attribute')
        depends[name] = value

    externals = [target for target in depends.values() if target not in depends]
    if len(externals) != 1:
        raise RuntimeError(
            f'Dependency chain {depends} should have one absolute dependency, found {externals}'
        )

    def dependent_of(name):
        found = [k for k, v in depends.items() if v == name]
        if len(found) != 1:
            raise RuntimeError(f'Expected one dependency of {name}, found {found}')
        return found[0]

    chain = [dependent_of(externals[0])]
    while len(chain) < len(names):
        chain.append(dependent_of(chain[-1]))
    return chain[-1]


def default_nx_class(translation: Translation, has_transformations: bool) -> str:
    instance = translation.instance
    type_name = component_type_name(instance)
    if type_name in COMPONENT_TYPE_NAME_TO_NEXUS:
        return COMPONENT_TYPE_NAME_TO_NEXUS[type_name]
    category = component_type_category(instance)
    if category in COMPONENT_CATEGORY_TO_NEXUS:
        return COMPONENT_CATEGORY_TO_NEXUS[category]
    for prefix, nx_class in COMPONENT_GROUP_TO_NEXUS.items():
        if type_name.startswith(prefix):
            return nx_class
    return 'NXcoordinate_system' if has_transformations else 'NXnote'


def fallback_body(translation: Translation, has_transformations: bool) -> dict:
    """The body for a component with no registered translator.

    Its NeXus class is guessed from the component type, and the handful of classes
    in :data:`NEXUS_CLASS_PARAMETERS` get their parameters filled from the McCode
    ones. Everything else becomes an empty group whose placement is still recorded.
    """
    nx_class = default_nx_class(translation, has_transformations)
    children = [
        translation.parameter_node(nexus_name, source=mccode_name)
        for nexus_name, mccode_name in NEXUS_CLASS_PARAMETERS.get(nx_class, {}).items()
    ]
    return component_body(nx_class, children)


def translate_instance(context: NexusContext, instance, index: int) -> tuple[dict, bool]:
    """Build one component's group node, and whether it should be suppressed.

    "No translator registered" and "a translator ran and returned ``None``" are
    different outcomes: the first falls back to a class guessed from the component
    type, the second means the instance is deliberately folded into some other node
    and must not appear in the file. The node is built either way so that relative
    placement chains through a suppressed instance still resolve.
    """
    translation = Translation(context, instance, index)
    transformations = context.transformations(instance)

    suppressed = False
    builder = context.registry.resolve_builder(instance)
    if builder is None:
        body = fallback_body(translation, bool(transformations))
    else:
        body = builder(translation)
        if body is None:
            suppressed = True
            body = fallback_body(translation, bool(transformations))

    node = group(body.get('name') or instance.name, body['nx_class'],
                 children=list(body['children']), attrs=body['attrs'])

    if transformations:
        only = list(transformations.items())[0] if len(transformations) == 1 else None
        if only is not None and only[1] is None:
            # Identity placement relative to a resolved absolute target
            node.setdefault('children', []).append(dataset('depends_on', only[0]))
        else:
            populated = {k: v for k, v in transformations.items() if v is not None}
            node.setdefault('children', []).append(
                group('transformations', 'NXtransformations', children=list(populated.values()))
            )
            node['children'].append(
                dataset('depends_on', f'transformations/{outer_transform_dependency(populated)}')
            )

    for direction, names in (('inputs', context.inputs(instance.name)),
                             ('outputs', context.outputs(instance.name))):
        if names:
            # nexusformat's attribute inserter automatically converts 
            # a singular list[str] to its held str. It might be nice to always
            # insert the list[str] here, but then we 'break' with the standard
            add_attribute(node, direction, names[0] if len(names) == 1 else names)

    return node, suppressed


def instrument_children(context: NexusContext) -> list[dict]:
    children = [
        dataset('name', context.instr.name),
        dataset('mcstas', str(context.instr)),
    ]
    for index, instance in enumerate(context.instr.components):
        node, suppressed = translate_instance(context, instance, index)
        # Registered even when suppressed, so a later component placed relative to it
        # can still resolve its transformation chain
        context.nodes[instance.name] = node
        if suppressed:
            context.suppressed.add(instance.name)
            continue
        children.append(node)
    return children


def to_nexus_structure(
        instr,
        origin: str | None = None,
        nxlog_root: str | None = None,
        absolute_depends_on: bool = False,
        registry=None,
        graph=None,
) -> dict:
    """Convert an assembled instrument into ESS NeXus Structure JSON.

    Parameters
    ----------
    instr:
        The ``mccode_antlr`` ``Instr`` an ``Assembler`` produced.
    origin:
        Name of the component to treat as the coordinate origin. Defaults to the
        instrument's sample-category component.
    nxlog_root:
        Where runtime parameter values are published, for link directives.
    absolute_depends_on:
        Rewrite relative ``depends_on`` values as absolute NeXus paths.
    registry:
        Translator registry; defaults to :data:`DEFAULT_NEXUS_REGISTRY`, which holds
        only the generic per-component-type translators. Pass an instrument-specific
        registry -- ``niess.nexus.bifrost.BIFROST_REGISTRY``, say -- to add its
        translators to this conversion alone.
    graph:
        A networkx DiGraph representing the possible particle path(s) through the
        instrument. A standard linear path will be constructed for @inputs and @outputs
        group attributes if this is not provided.
    """
    context = NexusContext(
        instr,
        nxlog_root=nxlog_root or DEFAULT_NXLOG_ROOT,
        origin_name=origin,
        registry=registry,
        graph=graph,
    )
    instrument = group('instrument', 'NXinstrument', children=instrument_children(context))
    entry = group('entry', 'NXentry', children=[instrument])

    if absolute_depends_on:
        absolutize_depends_on(entry, '')

    return {'children': [entry]}
