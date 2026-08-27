"""What niess wrote a component from, recorded on the component it emitted.

Every McStas instance niess emits carries a `niess_provenance` METADATA block naming the
niess class and instance behind it. This module is both halves of that: writing it during
emission, and reading it back when something that has only the emitted instrument needs to
know what it came from.

The namespace string in that block is literally this module's own name, and
`niess_source_type` is what puts a class's `__module__` into the emitted file -- so the
frozen `.instr` goldens in `tests/data/baseline` pin the import path of every component
class. Moving `niess/components/guide.py` changes emitted text; moving this module changes
the namespace every previously-written file is recognised by. Neither is a rename to make
casually.

Below `niess.dispatch`, which resolves a translator from what it reads here, and therefore
below every target. Writing happens through `add_niess_metadata`, called from the
components themselves.
"""
from __future__ import annotations

from dataclasses import dataclass
from json import dumps, loads
from typing import Any

from mccode_antlr.instr import Instance


NIESS_PROVENANCE_METADATA_NAMESPACE = 'niess.provenance'
NIESS_PROVENANCE_METADATA_NAME = 'niess_provenance'
NIESS_PROVENANCE_METADATA_MIMETYPE = 'application/json'
NIESS_PROVENANCE_METADATA_SCHEMA_VERSION = 2

#: Schema 1 spelled these for NeXus, which was never the only reader: chopcalc and tof
#: dispatch on them too, and neither has anything to do with NeXus. Schema 2 says what
#: they are. A file written by an older niess is still read.
_RENAMED_IN_SCHEMA_2 = {
    'nexus_group_id': 'disc_group_id',
    'nexus_group_index': 'disc_group_index',
}
_RENAMED_ROLES = {
    'nexus-group-primary': 'disc-opening-primary',
    'nexus-group-member': 'disc-opening-member',
}


@dataclass(frozen=True)
class NiessProvenance:
    namespace: str
    schema_version: int
    source_type: str
    source_name: str
    role: str
    extra: dict[str, Any]

    @classmethod
    def from_instance(cls, instance) -> NiessProvenance | None:
        payload = read_niess_metadata(instance)
        if payload is None:
            return None
        extra = dict(payload.get('extra', {}))
        for old, new in _RENAMED_IN_SCHEMA_2.items():
            if old in extra and new not in extra:
                extra[new] = extra.pop(old)
        role = payload.get('role', 'physical-component')
        return cls(
            namespace=payload['namespace'],
            schema_version=payload['schema_version'],
            source_type=payload['source_type'],
            source_name=payload['source_name'],
            role=_RENAMED_ROLES.get(role, role),
            extra=extra,
        )


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


def add_visit_metadata(visit, instance, source=None, **kwargs):
    """Write provenance for one emitted instance, unless this emission opted out.

    Every McStas emitter on the walk goes through here rather than calling
    `add_niess_metadata` directly, so that "emit without the niess METADATA blocks" is
    one decision made once at `to_mccode` rather than a flag each of seven call sites
    has to remember to honour -- and so that a translator added later cannot forget it.
    """
    if not getattr(visit.context, 'provenance', True):
        return instance
    return add_niess_metadata(instance, source, **kwargs)
