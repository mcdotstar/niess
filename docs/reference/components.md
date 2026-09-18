# Components

Everything in `niess.components`, and the McStas component each one emits. Use this
when mapping a `.instr` `TRACE` onto niess classes.

Every class takes at least `name`, `position` (a scipp vector) and `orientation` (a
scipp quaternion), and is built from a calibration dictionary with
`SomeClass.from_calibration({...})`.

## Sources

| niess class | emits | calibration keys |
| --- | --- | --- |
| `ESSource` | `ESS_butterfly` | `sector`, `beamline`, `height`, `cold_fraction`, `focus_distance`, `focus_width`, `focus_height`, `cold_performance`, `thermal_performance`, `wavelength_minimum`, `wavelength_maximum`, `latest_emission_time`, `n_pulses`, `accelerator_power` |

`wavelength_minimum` and `wavelength_maximum` accept a McCode instrument-parameter
specification string such as `'source_lambda_min/"angstrom" = 0.75'` instead of a
value, which turns them into run-time arguments of the generated instrument.

## Guides

| niess class | emits | calibration keys |
| --- | --- | --- |
| `StraightGuide` | `Guide_gravity` | `length`, `width`, `height`, `m` (or `left`/`right`/`top`/`bottom`) |
| `TaperedGuide` | `Guide_gravity` | `length`, `in_width`, `out_width`, `in_height`, `out_height` (or `width`/`height` for both ends), m-values as above |
| `EllipticGuide` | `Elliptic_guide_gravity` | `length`, `horizontal`, `vertical` (each `{major, minor, offset}` or `{in, out, midpoint\|entry\|exit}`), m-values as above |
| `StraightGuides`, `TaperedGuides` | one instance per segment | a dictionary of segment dictionaries |

`EllipticGuide` also accepts an array `length` with tuple m-values, which emits a
segmented guide with `DECLARE`d arrays.

## Apertures

| niess class | emits | calibration keys |
| --- | --- | --- |
| `Jaw` | `Slit` | `width`, `height` |
| `Slit` | `Slit` | `width`, `height` |

Both are *run-time adjustable*, which is the point of them: `Jaw` declares the
instrument parameters `{name}_l` and `{name}_r`, and `Slit` declares those plus
`{name}_b` and `{name}_t`. Their openings become links in the NeXus output rather than
fixed numbers.

## Choppers

| niess class | emits | calibration keys |
| --- | --- | --- |
| `DiscChopper` | one `DiskChopper` **per opening** | `radius`, `angle` or `windows`, `frequency` or `velocity`, `delay`, `width`, `height`, `zero_angle`, `beam_angle` |

A disc chopper's `position` is its **spindle**; the emitted `AT` is the point the beam
crosses the disc. `zero_angle` and `beam_angle` say where that point is — measured
counter-clockwise about +z, the first from the local +y axis to the disc's zero mark and
the second from the mark to the beam — and the vector between the two follows from them,
along with the rotation the emitted component carries so the disc ends up on the correct
side of the beam. Both default to zero, which puts the beam at the top of the disc; a disc
hanging above the beam has `beam_angle = 180`.

There is no `offset` to give. It was a field until the angles replaced it, and a
calibration that still sets one is refused rather than ignored — reading a placement
instruction as though it were absent would move the disc off the beam, where it absorbs
every neutron without saying so. `disc_beam_offset` is the one formula, and calibration
code that knows where the beam runs and needs the spindle negates what the chopper
derives going the other way.

`DiscChopper` declares `{name}speed` and `{name}delay` as instrument parameters.

McStas' `DiskChopper` describes `nslit` **identical, evenly spaced** openings and nothing
else, so a disc whose openings are neither is emitted as one `DiskChopper` per opening —
sharing one speed and delay, placed in a McStas `GROUP` so a neutron passes if it clears
*any* opening, and tagged so `niess.nexus.via_instr` rebuilds them as a single
`NXdisk_chopper` — reading the tree there is nothing to rebuild, since the disc was never
split. A
disc with one opening is one component under its own name, which is what a disc chopper
has always been. See
[composites](../how-to/new-instrument-submodule.md#composites-when-one-object-is-several-components).

`windows` (`slit_edges`) are measured **from the zero mark**: an even number of increasing
values, two per opening, positive counter-clockwise facing +z, with a final edge beyond
360 where the last opening straddles the mark. Giving `angle` instead is shorthand for one
opening centred on the beam, `beam_angle ± angle/2` — so `angle = 170` on a disc hanging
above the beam is `[95, 265]`, whose centre is the beam and whose emitted `delay` is
therefore the disc's own.

Edges are not required to be positive, and one may be written a turn late: an opening
centred on a beam at `beam_angle = 0` straddles the mark, and `[-85, 85]` says so more
plainly than `[275, 445]`. `NXdisk_chopper` is stricter — positive, increasing, opening
edge first, and only the *final* edge past 360, which happens exactly when the last slit
crosses the mark — so the NeXus writer puts them in that order, and writes
`top_dead_center` and `beam_position` alongside them so the frame is recorded.

That reordering rotates which slit comes first rather than shifting the list: the wrap
belongs to one slit, so adding 360 to every edge would carry the others out past it.
`[-10, 10, 60, 90]` is written `[60, 90, 350, 370]`, not `[350, 370, 420, 450]`.

### The emitted `AT` and `ROTATED` are not the disc's placement

A McStas `DiskChopper` expects its component origin **on the beam**, and always draws its
disc *below* that origin. So the emitted component is both moved — by `beam_offset()`,
from the spindle onto the beam — and turned, by `zero_angle + beam_angle` about z, for the
disc to land on the right side. Both are properties of the target, not of the chopper.

Both are recorded in the component's provenance, as `mccode_frame_offset` (metres) and
`mccode_frame_rotation` (a rotation vector in degrees), and `niess.nexus.via_instr` takes
them back out. An `NXdisk_chopper` is therefore centred on the **spindle**, carrying the disc's own
orientation — the placement the calibration gave — while McStas still gets the beam
crossing it needs:

| | McStas | NeXus |
| --- | --- | --- |
| origin | beam crossing | spindle |
| orientation | `orientation * Rz(zero_angle + beam_angle)` | `orientation` |

Without this the file would state the turn twice, once as a real rotation of the disc and
once as `beam_position`, and a reader combining them would place the mark `beam_position`
degrees from where it is; and the disc would sit `radius - height/2` off its own axis.

Any component may do this. `Component.__mccode_offset__` and
`Component.__mccode_frame_rotation__` report the difference between what is emitted and
what the object is, and are zero unless a subclass moves or turns its own emission.

`delay` is a time, not an angle: it is when an opening's centre is at the beam, which is
what McStas' `DiskChopper` acts on and what a real chopper is set with. The component
also accepts a `phase` in degrees, but only converts it to a delay and then ignores it
([McCode#2347](https://github.com/mccode-dev/McCode/issues/2347) covers the two not being
exact inverses), so niess emits `delay` and never `phase`.

## Monitors

All monitors emit `Frame_monitor` and attach a da00 histogram-stream configuration as
`METADATA`, published to `{instrument}_beam_monitor` unless
[told otherwise](../how-to/nexus-structure.md#choosing-how-a-monitor-streams).

| niess class | calibration keys |
| --- | --- |
| `FissionChamber` | `width`, `height`, `thickness` |
| `He3Monitor` | `radius`, `length`, `pressure` |
| `BeamCurrentMonitor` | `width`, `height`, `thickness`, `sample_rate` |
| `GEM2D` | `width`, `height`, `thickness`, `x_strips`, `y_strips` |

`BeamCurrentMonitor`'s `sample_rate` sets its time binning. `GEM2D`'s strip counts are
accepted but not yet used in the emitted component.

## Filters and attenuators

| niess class | emits | calibration keys |
| --- | --- | --- |
| `NCrystalFilter` | `Filter_sample` | `width`, `height`, `length`, `composition`, `temperature` |
| `Attenuator` | `Filter_sample` | as `NCrystalFilter` |
| `OrderedFilter` | `Filter_sample` | as `NCrystalFilter`, plus `tau` |
| `RadialFilterCollimator` | `Radial_col_filter` | radii, `composition`, `temperature` |

`Attenuator` adds an `int {name}_in = 0` instrument parameter and a matching `WHEN`, so
it can be moved in and out of the beam at run time. `RadialFilterCollimator` needs the
`mcdotstar/mcstas-radial-filter-collimator@main` component registry.

## Declared but not implemented

!!! warning "These emit an `Arm`"

    The classes below have no `__mccode__`, so they inherit `Component`'s, which emits
    an `Arm`. Some are abstract bases you are meant to subclass; the rest are simply
    unfinished. Either way, placing one in an instrument silently gives you a bare
    coordinate frame where you expected a component.

| niess class | why |
| --- | --- |
| `Aperture`, `Chopper`, `Guide`, `Filter` | abstract bases — use a concrete subclass |
| `Moderator` | a stub |
| `Collimator`, `SollerCollimator`, `RadialCollimator` | declared, not implemented |
| `FermiChopper` | declared, not implemented |

If you need one of the unimplemented ones, writing it is three methods — see
[Build a new instrument submodule](../how-to/new-instrument-submodule.md#writing-a-component).

## Not placed directly

`Wire`, `DiscreteWire`, `DiscreteTube`, `He3Tube`, `IdealCrystal` and `Crystal` are
building blocks used *inside* composites such as `niess.bifrost`'s detector triplets,
rather than placed in a beamline themselves. `DirectSecondary` and `IndirectSecondary`
are data-reduction views produced by `Tank.to_secondary()`, not conversion targets.
