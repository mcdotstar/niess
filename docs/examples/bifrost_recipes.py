"""Change BIFROST the way a McStas user would edit its .instr, but in niess."""
from pathlib import Path


def component_order(instrument) -> list[str]:
    """The emitted component names, in beam order, across the whole %include tree."""
    from niess.mccode import to_mccode
    return [c.name for c in to_mccode(instrument).components]


def main(outdir: Path) -> None:
    # --8<-- [start:sample]
    from niess.bifrost.bifrost import instrument
    from niess.bifrost.samples import Cylinder, sample, vanadium

    # a vanadium rod, 5 mm across and 20 mm tall, in place of the empty `sample` Arm
    rod = Cylinder(radius=0.0025, height=0.02)
    bifrost = instrument(sample=sample(vanadium(rod)))
    # --8<-- [end:sample]
    assert 'vanadium_analyzers' in component_order(bifrost)

    # --8<-- [start:calibration]
    from niess.bifrost.bifrost import instrument
    from niess.bifrost.parameters import primary_parameters

    calibration = primary_parameters()
    # m=3.5 side walls on all 47 straight-guide units, one COMPONENT line each in the .instr
    for name, unit in calibration['straight'].items():
        if name.endswith('_straight'):
            unit['left'] = unit['right'] = 3.5
    bifrost = instrument(calibration)
    # --8<-- [end:calibration]
    straight = bifrost.parts[0].content.straight
    assert straight.unit_29_straight.left == 3.5
    assert straight.unit_29_straight.top != 3.5

    # --8<-- [start:resection]
    import msgspec
    from msgspec.structs import replace
    from niess.components import Section

    def resection(section, parts: dict):
        """`section` with `parts` as its components, in this order -- which is beam order.

        niess has no API for changing what a section contains: its components are the
        fields of its class. This makes a stand-in class with the same name, which is
        what McStas names the section's %include file after, and the same underscore
        extras, and fills it.
        """
        extras = [(f.name, f.type, getattr(section, f.name))
                  for f in msgspec.structs.fields(section) if f.name.startswith('_')]
        cls = msgspec.defstruct(type(section).__name__,
                                [(n, type(p)) for n, p in parts.items()] + extras,
                                bases=(Section,), kw_only=True)
        return cls(**parts)

    def with_primary_section(bifrost, name: str, section):
        """`bifrost` with the primary spectrometer's section `name` replaced."""
        mount, *others = bifrost.parts
        primary = replace(mount.content, **{name: section})
        return replace(bifrost, parts=(replace(mount, content=primary), *others))
    # --8<-- [end:resection]

    # --8<-- [start:insert]
    from scipp import vector
    from niess.bifrost.bifrost import instrument
    from niess.components.opaque import Opaque

    bifrost = instrument()
    straight = bifrost.parts[0].content.straight
    after = straight.bandwidth_monitor
    # 10 cm downstream of the bandwidth monitor, along the guide; positions in a guide
    # section are in the instrument's coordinates, as in the .instr
    psd = Opaque(name='my_psd', mccode_type='PSD_monitor',
                 mccode_parameters={'nx': 100, 'ny': 100, 'filename': '"my_psd.dat"',
                                    'xwidth': 0.1, 'yheight': 0.1, 'restore_neutron': 1},
                 position=after.position + after.orientation * vector([0, 0, 0.1], unit='m'),
                 orientation=after.orientation)
    parts = {}
    for name, part in straight.to_dict().items():
        parts[name] = part
        if name == 'bandwidth_monitor':
            parts['my_psd'] = psd
    bifrost = with_primary_section(bifrost, 'straight', resection(straight, parts))
    # --8<-- [end:insert]
    order = component_order(bifrost)
    assert order.index('bandwidth_monitor') + 1 == order.index('my_psd')

    # --8<-- [start:remove]
    from niess.bifrost.bifrost import instrument

    bifrost = instrument()
    expanding = bifrost.parts[0].content.expanding
    parts = {name: part for name, part in expanding.to_dict().items()
             if name != 'overlap_monitor'}
    bifrost = with_primary_section(bifrost, 'expanding', resection(expanding, parts))
    # --8<-- [end:remove]
    assert 'overlap_monitor' not in component_order(bifrost)
