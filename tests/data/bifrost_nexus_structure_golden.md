# BIFROST NeXus Structure golden baseline

`bifrost_nexus_structure_golden.json.gz` is the output of `moreniius` (the package
`niess/nexus/` replaces) for the BIFROST instrument in `bifrost.instr.json.gz`, captured
before the port so there is a regression target that outlives `moreniius`.

Regenerated with:

```python
from moreniius import MorEniius
from moreniius import additions          # registers the BIFROST-specific translators
me = MorEniius.from_mccode(instr, origin='sample_origin', only_nx=False,
                           absolute_depends_on=False)
json.dumps(me.to_nexus_structure(), indent=2, sort_keys=True)
```

Importing `moreniius.additions` matters: it is imported only inside
`moreniius.nexus_structure.to_nexus_structure()`, so a golden captured through
`MorEniius.from_mccode` alone silently omits every BIFROST translator, leaving all 45
analyzers and 45 detector triplets as empty `NXcoordinate_system` groups. `moreniius`'s
own `tests/test_bifrost_nexus_structure.py` calls `from_mccode` directly and therefore
never exercised those translators either.

## Parity

`niess.nexus.to_nexus_structure` reproduces this file's structure: identical component
names in identical order, and a matching `NX_class` census (132 `NXcomponent` where the
golden has 132 `NXcoordinate_system` — see difference 8 — 119 `NXguide`, 45 `NXcrystal`,
45 `NXdetector`, 6 `NXdisk_chopper`, 5 `NXmonitor`, 5 `NXaperture`, 1 `NXmoderator`,
2 datasets).

Leaf differences remain in the categories below; every one is accounted for, none is
unexplained. Categories 1-3 and 6 date from the original port; 4 and 5 are later
corrections to BIFROST-specific translators; 7 is the move from chopper `phase` to
chopper `delay`.
`tests/test_nexus_bifrost_golden.py` asserts exactly this classification, so a new
difference fails the suite rather than passing unnoticed.

## Classified differences

### 1. Flattened `OFF_GEOMETRY` groups — 540 differences (90 `Guide_gravity` × 6 keys)

**A `moreniius` bug that this port fixes.** `moreniius.mccode.instr.NXInstr.expr2nx`
contains

```python
if not isinstance(expr, str) and hasattr(expr, '__iter__'):
    return [self.expr2nx(x) for x in expr]
```

and a `nexusformat` group *is* iterable — over its child **names**. Any group routed
through `make_nx` is therefore replaced by a list of strings. `guide_translator` passes
its `NXoff_geometry` through `make_nx`, so the golden records

```json
{"module": "dataset", "config": {"name": "OFF_GEOMETRY", "type": "string",
                                 "values": ["vertices", "winding_order", "faces"]}}
```

— the geometry itself is gone. This port emits the real `NXoff_geometry` group with its
`vertices`, `winding_order` and `faces` datasets.

Only translators that go through `make_nx` are affected. `elliptic_guide_gravity_translator`
and `monitor_translator` construct their group directly, so the 29 elliptic guides and
5 frame monitors kept real geometry — and this port reproduces those 34 groups exactly,
byte for byte. The asymmetry is visible within the golden itself: 34 components carry
real `NXoff_geometry` groups while the 90 `Guide_gravity` instances carry a list of
three strings.

### 2. Flattened `NXpositioner` groups — 180 differences (5 `Slit` × 6 positioners × 6 keys)

Same root cause. `slit_translator` builds one `NXpositioner` per aperture dimension and
passes them through `make_nx`, so each collapses to `{"values": ["value"]}`. This port
emits proper `NXpositioner` groups containing `name` and `value`.

The golden lists only `value`, not `name`: `nexusformat` took the translator's `name`
field for the group's own name rather than storing it as a child, so that dataset was
lost before the flattening even happened. This port emits both.

### 3. `detector_number` dtype — 45 differences (one per detector triplet)

The golden says `int64`, this port says `int32`. `moreniius`'s own translator writes
`np.array(detector_number).astype('int32')`, so int32 is the author's stated intent; its
writer then discarded it, because `convert_types` calls `.tolist()` and reads the dtype
off the resulting Python `int`. This port honours the declared dtype.

`cylinders` is deliberately **not** narrowed: the registered translator passes a plain
Python list, expressing no int32 intent, so it stays `int64` and matches the golden.

### 4. `segment_rows` — 45 differences (one per analyzer)

The golden holds the **string `"None"`**: `moreniius` read a `NV` parameter that
`Monochromator_Rowland` does not define, got `None` back, and its writer stringified
it. The component is a single row of `NH` horizontal segments, so this port writes the
integer `1`.

### 5. Detector pixel pitch — 135 + 4500 differences (`geometry/vertices`, `y_pixel_offset`)

`moreniius` computed the half-pixel length as `height / (no + 1) / 2`, an off-by-one
that treats the `no + 1` bin *edges* as if they were pixels. The component itself bins
with `linear = floor(no * ty)` over `ty` normalised across the full tube `height`
(`Detector_tubes.comp`), so there are exactly `no` bins of length `height / no`, centred
at `-height/2 + (k + 0.5) * height/no`.

The correct half-pixel is therefore `height / no / 2`, which this port uses. It fixes
two things at once: pixel centres now sit exactly on the component's own bin centres
(verified to 4e-17), and the single shared cylinder is exactly one pitch long instead of
~1% short, which had left a 23 um dead gap between every pair of adjacent pixels.

Note `dead_length` does not enter here: the component applies it as a weight taper near
the tube ends (`p *= end_steps(...)`), not as a change to the binning, so the pixel grid
covers the full `height`.

### 6. `mcstas` instrument source — 1 difference

The verbatim `str(instr)` dump differs by a single trailing newline, which `nexusformat`
stripped. Cosmetic.

### 7. `NXdisk_chopper` timing — 36 differences (6 choppers × 6 keys)

The golden writes `phase` in degrees; this port writes `delay` in seconds. McStas'
`DiskChopper` acts on `delay` alone — `phase` is converted to one in INITIALIZE and is
otherwise dead in TRACE — and `delay` is what the real choppers are set with, so it is
what `niess` emits and what the translator reads.

The comparison walks children positionally, so all 36 differences are the one node:
converted `delay` against golden `phase`, six keys apiece.

The values differ too, and not just in units. `bifrost.instr.json.gz` is a *pre-change*
`niess` output: its choppers carry `nu=Symbol('<name>speed')` and
`phase=Symbol('<name>phase')` with no `delay` at all. So the translator reads
`DiskChopper`'s own default and writes `delay: 0.0` where the golden has an `NXlog` link
to `<name>phase`. That is the accepted cost of emitting `delay` *instead of* `phase`
rather than both: an instrument that phases its choppers in degrees does not survive the
round trip. It only affects instruments written against the old convention — a BIFROST
rebuilt from `niess.bifrost.parameters` declares `<name>delay/"s"` and translates to a
proper `NXlog` link.

### 8. Reference frames and beam-path flow — the NXDL conformance pass

Two changes made together, both to satisfy a static NeXus checker reading the NXDL.

`NXcoordinate_system` describes the axes of a coordinate system, not a thing standing in
one, and `NXinstrument` does not list it among the children it accepts. The 132 groups
that are only a place — a declared frame, a sample position, a window — are now
`NXcomponent`, the base class every instrument component extends, each carrying a
`description` that says it is a reference frame.

`inputs` and `outputs` were written as group attributes. `NXcomponent` declares them as
*fields*, so every class extending it inherits them as fields; a validator reading the
NXDL rejects them written any other way. They are now datasets.

Neither change moves any value: the same names are recorded, for the same components, in
the same order.

## Not represented here

The BIFROST instrument parameterises its components with *instrument* parameters, not
DECLARE'd variables, so it does not exercise the DECLARE constant-folding fix. That is
covered by `tests/test_nexus_declare_variables.py`.
