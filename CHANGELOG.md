# Changelog

Notable changes to niess, newest first.

Versions follow [semantic versioning](https://semver.org/), with the pre-1.0 caveat that a
minor release may still remove things. 0.6.0 does, so it is a minor bump rather than a
patch; everything removed is listed below with what replaces it.

<!-- --8<-- [start:releases] -->
## Unreleased

### Added — `niess.scaffold`, and a `.instr` migration path

Removing the instrument-reading routes (below) left no way in from a McStas file at all.
This is the way back in, and it is a different kind of tool: not a second front-end into
every target, but a **one-way source generator**. It reads a `.instr` and writes a niess
submodule you own and edit, so what runs afterwards is ordinary niess source and there is
still exactly one path into each target.

```console
$ niess-scaffold my_instrument.instr -o src/niess --origin sample
```

It resolves every placement, maps the components whose McStas type *determines* a niess
class, wraps the rest in `Opaque`, and refuses to write anything unless the module it
generates places every component where the `.instr` does.

Be clear about the scale of what it does: for a real instrument it maps a small fraction
of the components — 8 of 50 for `ESS_IN5_reprate`. The rest become `Opaque` and the report
lists them, most frequent first. That list is the point of the tool as much as the code
is.

`docs/how-to/translate-an-instr.md` now documents the tool and, more usefully, the four
things it cannot do.

### Added — `niess.components.Opaque`

A McStas component niess has no class for, carried through verbatim: it holds a component
type name and arguments and emits exactly that, with role `unmodelled-component`.

It exists because the alternative was worse. A `Component` subclass with no `__mccode__`
inherits one that emits a bare `Arm`, so an unmodelled component silently became a
coordinate frame and the instrument quietly changed meaning.

### Fixed — a run-time parameter passed to a component by its declaration

`Component.to_mccode` substituted `str(InstrumentParameter)` for an
`InstrumentParameter`-valued entry in a component's parameter dictionary. That is the
parameter's *declaration* — `slit_width/"m"=0.03` — which the assembler then re-parsed as
arithmetic, giving `slit_width*1.0/"m"`. It now substitutes the name.

No shipped component reached this: `Aperture` and the rest pass `.name` themselves. It was
`Opaque` that first handed over the object.

### Changed — BIFROST's discs are chopper-lib `NXdisk_chopper` components

A disc is now emitted as one `NXdisk_chopper` from
[`mcstas-chopper-lib`](https://github.com/mcdotstar/mcstas-chopper-lib) rather than one
McStas `DiskChopper` per opening, and its openings go into the instrument's `DECLARE` as
an array the component and chopper-lib's band arithmetic both read. Each disc gains a
`{disc}park_angle` run-time knob alongside `{disc}speed` and `{disc}delay`; nothing is
removed. `NXDiskChopper` is the class, `DiscChopper` remains for the `DiskChopper` route.

The beam crossing moves. `disc_beam_offset` now takes the aperture's *width* into account:
the reach is the chord `sqrt(radius² - (width/2)²)`, not the radius, so the far corners of
the aperture sit on the disc circumference instead of overhanging it. BIFROST's four
30.4 mm discs move 0.330 mm and its two 60 mm bandwidth discs 1.288 mm. It is degenerate
with the old rule at zero width. Everything after `radius` is keyword-only now, because
inserting `width` ahead of `height` silently changed what a positional call meant.

**chopper-lib 4.2.1 or newer is required**, raised from 4.1.0. `niess.chopcalc` calls
`chopper_wavelength_limits`, which goes through the `range_set_sort` that until 4.2.1
"gave different answers on different platforms, which is how a chopper train's admitted
band came out 0.098 Å wide on Windows and 1.906 Å on Linux for the same discs". The struct
layout has been stable since 4.0.0, so an older library links and runs — it just answers
the question wrong, and differently per host. The emitted `#error` guard says so.

### Fixed — every target sees a disc again

`NXDiskChopper` was added as a *sibling* of `DiscChopper` rather than a subclass, and
`niess.tof` and `niess.nexus` both selected discs with `isinstance(x, DiscChopper)`. An
unregistered type falls through rather than failing, so both went quiet instead of loud:

- `chopper_specs` returned `()`. A BIFROST `tof` model had no choppers at all, and the
  instrument reported that it "declares `['source_lambda_max', 'source_lambda_min']`"
  when it declares eighteen chopper knobs besides.
- Every disc was written to NeXus as a bare reference frame carrying a description — no
  `slits`, `slit_edges`, `rotation_speed`, `delay` or `radius`. BIFROST's file contained
  **zero** `NXdisk_chopper` groups, which is what `mccode-plumber` looks for to wire a
  chopper's PVs to the forwarder.

The knobs, the openings and the controller now live on `Chopper`, so there is one of each:
`speed_parameter`/`delay_parameter`/`park_parameter` all return an `InstrumentParameter`
(one class returned a bare name, the other a parameter), and `DISC_CHOPPERS` names the two
disc classes so no caller has to remember there are two.

### Fixed — three defects the migration left behind

- **A disc's edges are two per opening.** `NXDiskChopper` paired *consecutive* edges, so
  the gap between two openings became an opening of its own: a three-slit disc reported
  five slits and emitted ten edge values where six were given. Invisible until now because
  the two pairings agree for a single opening, and every BIFROST disc has one.
- **`niess.chopcalc` emitted invalid C** — `free(train[0].edges;`, with no closing paren.
  Only instruments whose rows own their edges emit that line, so BIFROST, whose rows are
  `DECLARE` arrays, never showed it. The emitted C is now checked for balanced delimiters.
- **`pv_root` and `tdc_channel`** are back on a disc, having been dropped in the retyping.
  Without them a file can only be written in simulated mode, so real-mode NeXus had
  quietly become unavailable for all of BIFROST.

### Changed — a NeXus structure the ESS checker accepts

The written file now passes the ESS structure checker, in either of two modes.
`to_nexus_structure(instrument, streams=...)` says where a driven axis's numbers come
from: `SIMULATED` (the default) writes the simulation's own parameter names, `REAL` writes
the EPICS positioners the components declare. One tree, two files.

Two fields go, and neither is a rename:

- **`zero_position` on an `NXdisk_chopper`.** `NXdisk_chopper` measures `slit_edges` *from*
  the top-dead-centre mark, so the mark is the origin of that frame rather than a number
  in it — writing the angle again alongside the edges it is the zero of says nothing the
  file does not already say. When the mark passes is a different question, and the
  `top_dead_center` log answers it.
- **`x_gap`/`y_gap` on an aperture.** They are `NXslit` fields; a jaw is an `NXaperture`.
  Only the driven edges are recorded, so a jaw's *fixed* height is now not in the file.
  If it is wanted it needs a home chosen on purpose.

`Aperture.__mccode_extra__` goes with them, for the same reason on the McStas side: a
jaw's edges are run-time parameters, so provenance repeating their width duplicated what
the instance already carries. The fixed height went unrecorded there too.

### Changed — BIFROST tags the channel at the cassette, not at a ring of slits

The nine radial filter-collimators move from one-per-channel up into the tank, share a
single McStas `GROUP` with the elastic monitor, and write `secondary_cassette` from their
own `EXTEND`. A neutron scatters in at most one of them, which is the tagging
`RadialSlitBank` existed to do — so the slit bank is gone, along with `slit_angles`,
`slit_width`, `slit_radius` and `SLIT_BOUNDARY_MARGIN`. The beam's branch point is the
sample now rather than a component inside the tank, which is where it always was
physically.

Two flow bugs went with it: `Tank.__niess_flow__` reported the monitor's path without ever
calling the monitor's own `__niess_flow__`, so the node existed only if something above
happened to draw an edge to it — `Tank.to_graph()` alone gave nine disconnected channels
and no monitor.

### Added — a composite may `GROUP` and `EXTEND` what it encloses

A McStas `GROUP` makes its members alternatives: a neutron is offered each in turn until
one does not absorb it. So it spans components that are separate objects and no one of them
can name it, and the same goes for the `EXTEND` recording which of them took the ray.
`McCodeContext` gains `groups` and `extends` beside the `whens` it already had — set by a
composite's `__mccode_enter__` against a descendant's path, applied by the leaf emitter.

This is not the disc chopper's pattern. A disc emits several instances *of itself*, so it
owns them and calls `GROUP` in its own loop. Here each part is a component in its own right
and has to be emitted by the registry, with the name, frame, placement and provenance the
walk supplies — a parent emitting its own children would bypass all of it.

### Fixed — an elliptic guide's widest point was in the wrong place

`EllipticGuide` evaluated its half-width at `offset - minor + z` where
`Elliptic_guide_gravity.comp` traces neutrons against `z - offset`: a sign error on the
offset, and a spurious `minor`. Both terms are small next to the major axis, so the result
stayed a plausible guide and read as more-or-less right — but the widest point of the
channel belongs at `z == offset`, and the sign put it at `-offset`, which for most of
BIFROST's guides is outside the guide entirely. **Across the 58 faces of the primary the
median error is 10% and the worst is 100%.**

`TaperedGuide` and `EllipticGuide` now have `__off__` and `__nexus_leaf__` alongside
`StraightGuide`'s, and the m-values move onto `Guide` so all three wind their faces the
same way — `[top, right, bottom, left]` per segment, one m-value each. The generic
`@translator(Guide)` is gone: it wrote `length` and scalar `m_left`/`m_right`/`m_top`/
`m_bottom`, none of which `NXguide` has.

### Changed — provenance schema 3 drops `source_name`

It could only ever repeat `instance.name`. Every writer passed the same string it had just
handed `assembler.component`, and `Instance` keeps that name verbatim since `add_component`
raises on a collision rather than renaming around it. Nothing read it —
`dispatch._resolve_local` resolves on `source_type` and `role`. What it carried was risk:
two copies of one name can disagree, and the copy in the metadata is the one that would
look authoritative when they did. `NiessProvenance.source_name` stays as an attribute, read
off the instance.

### Added — `niess.components.Motor`, a driven axis that says where its numbers come from

A `Motor` carries a name, a unit, a default, and the Kafka `source`/`topic` its values
arrive on. `Motor.parameter()` gives the `InstrumentParameter` a run sets, and the NeXus
target writes it as the `NXlog` an `NXpositioner` value or an `NXtransformations` entry
needs — attributes for `depends_on`, `transformation_type` and `vector` on the group, and
the stream module carrying the unit twice (`value_units` for the f144 contract, a `units`
attribute for a reader resolving the chain).

### Fixed — a dataset module the ESS file-writer can read

Dataset modules were written with `type` where the ESS file-writer schema requires
`dtype`. One key, every static dataset in every file.

### Changed — BIFROST's radial slit bank is no longer written to NeXus

It was a single `NXslit` reporting ten slits, with an angular width recorded in `x_gap`,
which is a length. Splitting it would not have helped: ten `NXslit`s would report ten
apertures that are not there, still in the wrong units, and a reduction would have to
learn to ignore them. **An absent thing says nothing; ten fabricated ones say something
false.**

There is no ring of slits at BIFROST's sample. It is how a neutron leaving the sample gets
tagged with the channel it entered — the emitted McStas component reports which opening it
passed, and everything downstream is gated on that. `slitDistance` being drivable, with a
default chosen to clear everything further out, is what a surface that is not there can
afford to do, and no CAD builder draws it.

It remains a niess object and McStas still emits it unchanged — the `.instr` goldens do
not move — because the beam really does divide there, and the particle flow has to say so.
The flow record now steps over unwritten nodes rather than naming only written ones, which
is what kept nine channels and a monitor from being left with nothing feeding them.

### Removed — the instrument-reading routes

Every target read the niess object tree *and* had a second implementation that read an
assembled `mccode_antlr` instrument, recovering what the tree states. The second one is
gone, in `niess.chopcalc`, `niess.tof`, `niess.brep` and `niess.nexus` alike — some 4000
lines. **Converting an instrument niess did not build is no longer supported.**

Reading a `.instr` still is: `niess.io.mccode.load_instr` parses one so its placements can
be inspected, which is what checking a niess submodule against the hand-written file it
replaces needs.

What this changes for a caller:

- `narrow_source_wavelengths` no longer finds its own chopper train. `chopper_train` is a
  required argument from `train_from_instrument`, and `source`, `skip`, `path_lengths`,
  `latest_emission` and `graph` moved with the searching.
- `niess.brep.via_instr.instrument_to_assembly`, `niess.tof.via_instr.to_tof_model`,
  `niess.nexus.via_instr.to_nexus_structure` and the `niess.nexus.via_instr` subpackage no
  longer exist.
- `Subject.extra` is gone: a guide states its `substrate` and `resolution` as fields, so
  a builder no longer reads them off a provenance tag.

### Fixed — two things only the removed route was doing

Both were bugs the parallel implementations had been hiding, and both are in the tree
route now:

- **`@inputs` / `@outputs`** were not written at all. McCode cannot say that a beam
  branches, so the removed route had to be handed the real flow as `graph=`; a niess
  instrument states it, and BIFROST's radial slits now record all ten paths leaving them.
- **`slit_edges`** were written as niess holds them, which is deliberately looser than
  `NXdisk_chopper` allows — `[-85, 85]` rather than `[275, 445]`. The conversion to the
  standard's order lived in the removed route. It is `DiscChopper.nexus_slit_edges` now,
  and `slit_angle` is written again alongside it.


Every conversion target now lives under its own subject name and reads the niess object
tree. The route that reads an assembled McStas instrument instead is kept, one
`via_instr` per package, and is what goes when converting a foreign `.instr` stops being
served. `niess.targets` is gone.

### Added

- **niess objects display themselves.** msgspec generates a repr from the fields, and a
  composite's fields are its whole subtree — a BIFROST `Instrument` came out at nearly
  300 000 characters, so typing its name flooded the terminal. `Instrument`, `Mount`,
  and every `Base` and `Section` now say what they are, what they contain and how big
  that is, in columns aligned across each set of siblings. A node small enough to say
  so also lists its own fields — one chopper gives its radius, speed and position, where
  a whole instrument lists its parts; `niess.display.PARAMETERS` overrides that
  judgement and `niess.display.show()` takes it per call. In a notebook `_repr_html_`
  renders the same tree as nested `<details>`, collapsed below the top level, so a
  thousand-node instrument opens where you want it.

### Changed — import paths

| was | is |
| --- | --- |
| `niess.targets.mccode.to_mccode` | `niess.mccode.to_mccode` |
| `niess.targets.nexus.to_nexus_structure` | `niess.nexus.to_nexus_structure` |
| `niess.targets.nexus.BIFROST_REGISTRY` | `niess.nexus.bifrost.BIFROST_REGISTRY` |
| `niess.targets.brep.to_assembly` | `niess.brep.to_assembly` |
| `niess.tof.tree.to_tof_model` | `niess.tof.to_tof_model` |
| `niess.chopcalc.tree.train_from_instrument` | `niess.chopcalc.train_from_instrument` |
| `niess.nexus.load_instr` | `niess.io.mccode.load_instr` |
| `niess.mccode` (Assembler helpers) | `niess.assembler` |
| `niess.mccode` (provenance metadata) | `niess.provenance` |
| `niess.nexus.{instrument,translators,registry,bifrost,expression,orientation,variables}` | `niess.nexus.via_instr.*` |
| `niess.brep.components` | `niess.brep.builders` (shapes), `niess.brep.via_instr` (the old walk) |
| `niess.tof.components` | `niess.tof.setup` (shared), `niess.tof.via_instr` (the old walk) |
| `niess.chopcalc.discovery` | `niess.chopcalc.paths` (shared), `niess.chopcalc.via_instr` |

### Changed — three names now mean the tree route

`niess.nexus.to_nexus_structure`, `niess.tof.to_tof_model` and `niess.brep.save_step`
each used to resolve to the instrument-reading implementation and now resolve to the
tree-reading one. They take an `Instrument` where they took an `Assembler` or an `Instr`.
The previous behaviour is `niess.nexus.via_instr`, `niess.tof.via_instr` and
`niess.brep.via_instr` respectively.

### Removed

- **`niess.__init__` re-exports.** `import niess` is a namespace; name the subject you
  want (`from niess.components import Crystal`, `from niess.instrument import Instrument`).
  This also stops `import niess` from loading the CAD target and every component class.
- **`niess.brep.registry`** and `DEFAULT_BREP_REGISTRY` — it had become a two-name alias
  of the registry it imported. The registry is `niess.brep.BREP_REGISTRY`.
- **`niess.tof.registry`** as a module: `NiessTofRegistry` and `DEFAULT_TOF_REGISTRY` are
  in `niess.tof.via_instr`, with the decorators that populate them.
- Dead code carried no further: `_provenance_value`, `_loft_rectangles`, `_loft_ellipses`
  and `_ellipse_span` in the BREP builders; `_import` and `_lazy` in the NeXus target.

### Fixed

- Importing the tree NeXus target no longer executes the whole instrument-reading one
  (`niess.nexus.structure` reached `..nexus.nodes`, which ran the old package `__init__`).
- Importing generic NeXus no longer imports `niess.bifrost`: the tree target called
  `register_bifrost()` at module scope, so one instrument's translators loaded whether or
  not anything asked. They register on import of `niess.nexus.bifrost`, as the
  instrument-reading route always did.
- `niess.tof` and `niess.chopcalc` no longer reach into the demoted route for shared
  arithmetic — `niess.chopcalc.paths` holds what both use, including the beam-path walk
  and `global_position`, which `niess.tof` had been importing as a private.

## 0.6.0

Choppers, twice over: described the way they are actually built and controlled, and then
put to work. A disc is now one class however many openings it has, set with a delay rather
than a phase, and placed by where its spindle is rather than by an offset someone worked
out by hand. Two new modules read that description — `niess.chopcalc` narrows a source to
the band its chopper train passes, and `niess.tof` flies neutrons through the train in a
notebook.

### Added

- **`niess.tof`** — `to_tof_model()` turns an emitted instrument into a ready-to-run
  [`tof.Model`](https://scipp.github.io/tof/), with every disc chopper and a detector at
  each monitor and at the sample. It returns a `TofSetup` rather than a bare model, which
  reports in a notebook table which run-time parameters were used and at what value, and
  `with_values()` turns one knob without rebuilding the rest. `pulses=` simulates more than
  one source pulse, which is what shows a disc running at half the source frequency doing
  its job. Install with `pip install 'niess[tof]'`.
- **`niess.chopcalc`** — `narrow_source_wavelengths()` emits a chopper-lib call into the
  instrument's `INITIALIZE` so the source samples only the band the choppers pass, which is
  free simulation speed. The band is computed at run time from the chopper parameters, so
  changing a delay on the command line recomputes it without rebuilding anything.
  `export_choppers=` publishes the train to `DECLARE` for a component that needs the
  chopper description itself rather than the band it implies.
- **A user-supplied particle-flow graph**, accepted by `to_nexus_structure()`,
  `narrow_source_wavelengths()`, `build_train()` and `to_tof_model()`. McCode has no way to
  say that a beam branches — its instruments are a list — so an instrument that splits at
  the sample, as BIFROST does, had every component past that point treated as fed by
  whichever happened to be declared before it. Passing the graph fixes both the `@inputs`
  written into NeXus and the flight paths measured through it. Omitting it derives the flow
  from declaration order, as before.
- **`zero_angle` and `beam_angle` on `DiscChopper`**, saying where the beam crosses the
  disc: counter-clockwise about +z, the first from local +y to the disc's zero mark, the
  second from the mark to the beam. A disc hanging above the beam is `beam_angle = 180`.
- **`windows` on `DiscChopper`** — slit edges from the zero mark, two per opening, for a
  disc whose openings are neither identical nor evenly spaced.
- **Extras**: `niess[tof]`, `niess[examples]` for the documentation's notebooks, and
  `niess[brep]`, which had been needed by `niess.brep` all along with no way to ask for it
  by name.
- **Documentation**: how-to guides for
  [narrowing the wavelength band](https://mcdotstar.github.io/niess/how-to/narrow-the-wavelength-band/)
  and [simulating a chopper cascade](https://mcdotstar.github.io/niess/how-to/simulate-a-chopper-cascade/),
  an API page for `niess.tof`, and a notebook joining chopcal, niess and tof on BIFROST.

### Changed

- **Disc choppers are set with a delay in seconds, not a phase in degrees.** A delay is
  what a real chopper is set with, it is what McStas' `DiskChopper` acts on, and unlike a
  phase it does not depend on which way the disc turns. `Chopper.phase` is now
  `Chopper.delay`, and the emitted instrument parameter `{name}phase` is `{name}delay`.
- **A disc chopper's `position` is its spindle.** The emitted `AT` is the point the beam
  crosses the disc, computed from `zero_angle` and `beam_angle`, along with the rotation
  that puts the disc on the correct side of the beam. Both are recorded in provenance and
  taken back out by `niess.nexus`.
- **NeXus output for disc choppers has changed**, in three ways: an `NXdisk_chopper` is
  centred on the spindle rather than on the beam crossing, it no longer carries the McStas
  frame twist as a real rotation of the disc, and its `slit_edges` are ordered as the
  standard asks. Compare files across this release rather than assuming they match.
- **chopper-lib 3.0.0 or newer is required** by `niess.chopcalc`, pinned as
  `mcdotstar/mcstas-chopper-lib@v3.0.0`, with a `#error` in the emitted C for anyone who
  overrides the registry with something older.

### Removed

- `MultiSlitChopper` — `DiscChopper` takes `windows` and emits one `DiskChopper` per
  opening, grouped, exactly as `MultiSlitChopper` did.
- `DiscChopper.offset` — give `zero_angle` and `beam_angle` instead. A calibration that
  still sets an offset is refused rather than ignored: reading a placement instruction as
  though it were absent would move the disc off the beam, where it absorbs every neutron
  without saying so.
- `DiscChopper.chopper_lib_parameters` — `niess.chopcalc` builds the chopper-lib
  description from the emitted instrument.

### Fixed

- **Rotations near ±90°.** `mccode_ordered_angles` extracted McCode's three angles by hand,
  with a gimbal-lock guard written for a different Euler convention than the formulas it
  guarded. 7 of 20000 random orientations came back as a *different* rotation, and exactly
  ±90° was handled by neither branch. It uses scipy now.
- **Components that move.** A component positioned by an instrument parameter raised out of
  `to_tof_model()` instead of being skipped, because the check for "is this a number yet"
  caught only `AttributeError` while `Expr.value` raises `NotImplementedError`. Secondary
  spectrometers on a movable tank convert now.
- **Multi-opening discs narrowed the band too little.** Such a disc was approximated by the
  single angular envelope spanning its first and last edges, so one whose openings reach
  right round admitted everything and was dropped. Describing each opening gets it back:
  for the three-slit disc in the test suite, 0.75–30 Å goes from not narrowed at all to
  2.20–13.08 Å.
- **`slit_edges` ordering.** `NXdisk_chopper` wants positive increasing edges starting with
  an opening edge, with only the final edge allowed past 360. That reordering rotates which
  slit comes first rather than shifting the list, so `[-10, 10, 60, 90]` is written
  `[60, 90, 350, 370]`, not `[350, 370, 420, 450]`.
- **The test suite passes without the optional extras**, which is what optional was supposed
  to mean. The documentation examples and notebooks skip when an extra is absent, and only
  then — an example broken any other way still fails.

### Migrating from 0.5.0

| 0.5.0 | 0.6.0 |
| --- | --- |
| `DiscChopper(..., phase=...)` | `DiscChopper(..., delay=...)`, in seconds |
| `{name}phase` run-time parameter | `{name}delay` |
| `MultiSlitChopper(..., windows=...)` | `DiscChopper(..., windows=...)` |
| `DiscChopper(..., offset=...)` | `DiscChopper(..., zero_angle=..., beam_angle=...)` |
| `chopper.chopper_lib_parameters()` | `niess.chopcalc.build_train(instrument)` |

A calibration dictionary carrying `offset` is refused with a message naming the
replacement, so an instrument submodule that has not been converted says so on the first
build rather than quietly placing a disc in the wrong place.

If you keep reference NeXus files, regenerate them: disc chopper geometry moved, for the
reasons under **Changed**.
<!-- --8<-- [end:releases] -->
