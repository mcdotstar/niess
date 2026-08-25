from __future__ import annotations

from json import dumps, loads
from typing import Any

from mccode_antlr.assembler import Assembler
from mccode_antlr.common import InstrumentParameter
from mccode_antlr.instr import Instance


NIESS_PROVENANCE_METADATA_NAMESPACE = 'niess.provenance'
NIESS_PROVENANCE_METADATA_NAME = 'niess_provenance'
NIESS_PROVENANCE_METADATA_MIMETYPE = 'application/json'
NIESS_PROVENANCE_METADATA_SCHEMA_VERSION = 2


def ensure_user_var(a: Assembler, dtype: str, name: str, description: str):
    """Ensure that particle struct parameter is declared"""
    a.ensure_user_var(f'{dtype} {name}; // {description}')


def declare_array(instrument: Assembler, element_type: str, name: str, description: str, values):
    instrument.declare_array(element_type, name, values)


def ensure_parameter(a: Assembler, data_type: str, name: str, description: str):
    """Ensure that a parameter is declared in the instrument"""
    a.parameter(f'{data_type} {name}; // {description}', ignore_repeated=True)


def ensure_runtime_line(a: Assembler, line: str):
    """Ensure that a runtime-defined parameter is declared in the instrument

        Utilizes the parser to define an `InstrumentParameter` object, which can have
        a string representation like:
            parameter_type parameter_name/"parameter unit" = default_value; // comment
        which gets truncated at the ';' (or '//' if ';' is missing) such that the comment
        is dropped.

        Each of parameter_type, parameter_unit, default_value and comment are optional,
        such that
            parameter_name
        is the minimally valid definition.
        If missing, `parameter_type` is equivalent to specifying 'double'.
        The default value depends on the type, but is typically 0.

        Repeated definitions of the same parameter are ignored, but inconsistent
        default, type, or units will raise an error.
    """
    return ensure_runtime_parameter(a, InstrumentParameter.parse(line))


def ensure_runtime_parameter(a: Assembler, par: InstrumentParameter):
    """Ensure that a runtime-defined parameter is declared in the instrument

    Repeated definitions of the same parameter are ignored, but inconsistent
    default, type, or units will raise an error.
    """
    held = a.instrument.get_parameter(par.name)
    if held is None:
        a.instrument.add_parameter(par)
        return
    if held != par:
        msg = f"Parameter {par.name} already defined"
        if held.value is not None:
            msg += f" with value {held.value}"
        if held.unit is not None:
            msg += f" {held.unit}"
        raise RuntimeError(msg)


def root_assembler(a: Assembler) -> Assembler:
    """The outermost Assembler of a (possibly nested) assembly.

    ``Assembler.included()`` builds a section as a child assembler whose own name is
    the section's, so anything naming itself after ``assembler.name`` inside a section
    picks up the section name rather than the instrument's. Walk to the root when the
    instrument as a whole is what is meant.
    """
    while getattr(a, 'parent', None) is not None:
        a = a.parent
    return a


def instrument_name(a: Assembler) -> str:
    """The name of the instrument being assembled, from anywhere in the hierarchy."""
    return root_assembler(a).name


def ensure_registry(a: Assembler, specification: str):
    """Ensure that a register-defined parameter is declared in the instrument

    Parameters
    ----------
    a : Assembler
    specification : str
        Any of the mccode_antlr.reader.registry supported formats,
        1. ``{resolvable folder path}``
        2. ``{name} {resolvable folder path}``
        3. ``{name} {resolvable url} {resolvable file path}``
        4. ``{name} {resolvable url} {version} {registry file name}``
        5. ``git+{url}@{version}`` or ``git+{url}@{version}#{registry-file}``
        6. ``{owner}/{repo}@{version}`` or ``{owner}/{repo}@{version}#{registry-file}``
    """
    from mccode_antlr.reader.registry import registry_from_specification as rfs
    reg = rfs(specification)
    if not reg:
        msg = f"Unable to construct registry from {specification}"
        if not 'http' in specification and '/' in specification and not '@' in specification:
            msg += " missing @{tag|branch|commit} in GitHub Actions style specification"
        raise RuntimeError(msg)
    if not reg in a.instrument.registries:
        a.instrument.registries += (reg,)


def niess_source_type(source: type | Any) -> str:
    typ = source if isinstance(source, type) else type(source)
    return f'{typ.__module__}.{typ.__qualname__}'


def niess_metadata_payload(
        *,
        source_type: str,
        source_name: str,
        role: str = 'physical-component',
        extra: dict[str, Any] | None = None,
):
    return {
        'namespace': NIESS_PROVENANCE_METADATA_NAMESPACE,
        'schema_version': NIESS_PROVENANCE_METADATA_SCHEMA_VERSION,
        'source_type': source_type,
        'source_name': source_name,
        'role': role,
        'extra': {} if extra is None else extra,
    }


def add_niess_metadata(
        instance: Instance,
        source: Any | None = None,
        *,
        source_type: str | None = None,
        source_name: str | None = None,
        role: str = 'physical-component',
        extra: dict[str, Any] | None = None,
):
    from mccode_antlr.common import MetaData

    if source is not None:
        source_type = niess_source_type(source)
        source_name = getattr(source, 'name', None) if source_name is None else source_name
        # Recorded here rather than by each caller: a component whose emitted frame is
        # turned relative to its own is the one thing an adapter reading the instrument
        # back cannot work out for itself, and there are two emission paths that would
        # each have to remember.
        turn = getattr(source, '__mccode_frame_rotation__', None)
        rotation = None if turn is None else turn()
        if rotation is not None and any(abs(a) > 0 for a in rotation):
            extra = dict(extra or {}) | {'mccode_frame_rotation': list(rotation)}
        shift = getattr(source, '__mccode_offset__', None)
        displacement = None if shift is None else [
            float(v) for v in shift().to(unit='m').value
        ]
        if displacement is not None and any(abs(v) > 0 for v in displacement):
            extra = dict(extra or {}) | {'mccode_frame_offset': displacement}

    if source_type is None or source_name is None:
        raise ValueError('Both source_type and source_name must be defined')

    payload = niess_metadata_payload(
        source_type=source_type,
        source_name=source_name,
        role=role,
        extra=extra,
    )
    metadata = MetaData.from_instance_tokens(
        instance.name,
        NIESS_PROVENANCE_METADATA_MIMETYPE,
        NIESS_PROVENANCE_METADATA_NAME,
        dumps(payload, separators=(',', ':')),
    )
    instance.add_metadata(metadata)
    return instance


def read_niess_metadata(instance: Instance):
    for metadata in reversed(instance.collect_metadata()):
        if metadata.name != NIESS_PROVENANCE_METADATA_NAME:
            continue
        payload = loads(metadata.value)
        if payload.get('namespace') != NIESS_PROVENANCE_METADATA_NAMESPACE:
            continue
        return payload
    return None
