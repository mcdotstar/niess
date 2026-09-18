# Narrow the wavelength band to what the choppers pass

A source samples uniformly across the band it is given, and a chopper train throws most of
that away. Every neutron absorbed at the first chopper cost something to create, so
telling the source to only sample wavelengths that can reach the sample is free simulation
speed.

`niess.chopcalc` works that band out from the instrument itself.

```python
--8<-- "narrow_band.py:narrow"
```

Call it once the instrument is complete — after every section and every hand-added
component, and before writing it out. It needs the top-level `Assembler`: a child from
`assembler.included(...)` merges into its parent only when the block exits, so a section's
own choppers are not visible from inside it.

## Why this is C rather than Python

The band depends on chopper speeds and delays, and those are run-time parameters — the
whole point of emitting `chopperspeed` and `chopperdelay` rather than numbers. So the
calculation cannot happen when the instrument is built. `chopcalc` emits a call to
[chopper-lib](https://github.com/mcdotstar/mcstas-chopper-lib) into the instrument's
`INITIALIZE` instead, which McCode runs *before* every component's own initialisation.
The source therefore reads the narrowed values, and

```shell
./teaching -n 1e7 chopperdelay=0.006
```

recomputes the band without rebuilding anything. The instrument says what it did:

```
niess.chopcalc: sampling 0.5 to 2.51491 AA instead of 0.5 to 10 AA.
```

## What it needs from the source

The wavelength limits have to be **instrument parameters**, because the generated C writes
through their addresses. In a niess calibration that means giving them as parameter
specifications rather than values:

```python
'wavelength_minimum': 'source_lambda_min/"angstrom" = 0.75',
'wavelength_maximum': 'source_lambda_max/"angstrom" = 30.0',
```

A literal is refused, with that fix in the message.

The source is found from the beam path — it is the one component neutrons enter at, so it
is a root of the particle flow graph. That matters because a wavelength monitor is not a
source but looks like one: `L_monitor`, `TOFLambda_monitor`, `DivLambda_monitor`,
`PolLambda_monitor` and `MeanPolLambda_monitor` all take `Lmin` and `Lmax`. Pass
`source='...'` when an instrument has more than one entry point.

## What it leaves out, and why that is safe

Leaving a chopper out of the calculation can only make the band **wider**, never narrower,
so it never discards a neutron that would have passed. That is what makes the following
conservative rather than wrong:

| left out | because |
| --- | --- |
| a disc in a McStas `GROUP` with no niess provenance | grouped discs are alternatives, not a series, and there are no slit edges to describe them with |
| a Fermi chopper | chopper-lib has no row shape that describes one |
| a disc whose speed, opening or delay is unset | there is no row to write |

One case stops the calculation altogether rather than approximating it: a chopper with
`isfirst=1` re-times neutrons instead of absorbing them, so every downstream delay is
measured from a different zero and the chopper-train model does not apply.

## Handing the train to a component

The narrowing builds its array inside a braced block in INITIALIZE. That is what keeps
`chopcalc_*` from colliding with anything else there, and it also means the array — and
the window arrays its rows point at — are gone before any component initialises.

A component that takes the train as a parameter needs it to last longer than that. Ask
for it by name:

```python
train = narrow_source_wavelengths(
    assembler, export_choppers='bifrost_choppers', strict=True)
```

which adds to DECLARE

```c
chopper_parameters * bifrost_choppers = NULL;
int bifrost_choppers_count = 0;
```

hands the train over at the end of the narrowing, and frees it in FINALLY. The count name
defaults to `f'{export_choppers}_count'`; pass `export_chopper_count=` to choose it. Both
are reported back on `train.export`.

The train is built on the heap whether or not anything else will read it, which is what
makes the handover a pointer assignment rather than a copy. It costs one allocation per
disc, and it means there is one construction path and one release — the same few lines,
emitted at the end of INITIALIZE when nobody else wants the train, and in FINALLY when
somebody does. Each row's slit edges go back before the row array either way, since freeing
the array alone would lose every edge array with it.

Pass `(double *) bifrost_choppers` to a component whose own parameter is declared that
way, which is the usual shape for handing a struct array through McStas.

`strict=True` is worth pairing with this. The default when a band cannot be worked out is
to warn and emit nothing, which for the narrowing alone is safe — the instrument just
samples the band it was given. A component that reads the train instead gets a NULL
pointer and a count of zero, so you want the exception.

## Discs with several openings

Every disc is described to chopper-lib by its **slit edges**, as a `chopper_parameters`
row pointing at a flat, increasing array of angles in degrees, two per opening — the same
array the `CollectorDiskChopper` component and the NeXus `NXdisk_chopper` standard use.

There is no conversion. The angles are the disc's own, measured from its top-dead-centre
mark in the order `slits()` gives them, and where the beam crosses the disc travels
alongside them as the row's `beam` field. chopper-lib 4.0.0 puts an edge at angle `a` on
the beam at

```
t(a) = delay + (beam - a) / (360 * speed)
```

so `{disc}delay` is when `beam_position` is on the beam, exactly as niess means it.

Up to chopper-lib 3.0.0 the row carried `beam_position - e` for each edge `e`, with the
pair reversed, because the library had no field for the crossing and expected the caller
to fold it in. A three-opening BIFROST disc went across as `(60, 80) (-50, -10)
(-280, -260)` — negative, out of order, and unrecognisable as the disc the component was
given. It now goes across as the disc's own edges.

The `speed` keeps its sign, and chopper-lib uses it signed — reversing a disc reflects its
openings about the delay. That is invisible for a single opening centred on the beam
crossing and matters for every other one. `chopper-lib` 4.0.0 is the minimum and the
generated C `#error`s against anything older, which matters because the sign of the angle
term reversed with the rename: an older library given the new numbers would place every
opening on the wrong side of `delay`.

Before chopper-lib could take several openings, a multi-opening disc was approximated by
its angular envelope — the span from its first opening's edge to its last — which admitted
the gaps between openings too. That is gone. A disc whose openings reach right round the
disc used to be dropped outright, because its envelope covered a full revolution and so
constrained nothing; described by its openings it constrains properly. For the three-slit
disc in the test suite, 20, 40 and 20 degrees wide, that is the difference between
narrowing 0.75–30 Å to nothing at all and narrowing it to 2.20–13.08 Å.

## Flight paths

Path lengths are walked along the beam — `Instr.build_flow_graph()`, then the summed
segments from the source — rather than measured straight, so a curved guide is followed
instead of cut across. A chopper's emitted `AT` is already the point where the beam crosses
its disc, which is what a niess `offset` converts to, so no further correction is needed.

If the beam has to turn sharply to arrive at a component, `chopcalc` says so: that usually
means the component is placed at its spindle rather than on the beam, which would also make
it absorb every neutron at run time. `path_lengths={'chopper': 15.02}` overrides a measured
path when the real one is known by other means.
