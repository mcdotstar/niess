"""Deprecated: the moderator classes are in `niess.components.moderator`.

`Source` became `Moderator` and `ESSource` became `ESSModerator`, because the component
is the moderator an instrument views, not the facility's source -- for ESS, the proton
accelerator. The old names still work here, with a `DeprecationWarning`, and will be
removed in a later release.
"""
from warnings import warn

_RENAMED = {
    'Source': 'Moderator',
    'ESSource': 'ESSModerator',
    'ESS_SOURCE_DURATION': 'ESS_SOURCE_DURATION',
}


def __getattr__(name):
    if name not in _RENAMED:
        raise AttributeError(f'module {__name__!r} has no attribute {name!r}')
    warn(f'niess.components.source.{name} is now '
         f'niess.components.moderator.{_RENAMED[name]}',
         DeprecationWarning, stacklevel=2)
    from . import moderator
    return getattr(moderator, _RENAMED[name])
