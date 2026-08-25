from __future__ import annotations
from typing import Any
from dataclasses import dataclass

from .mccode import read_niess_metadata

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
