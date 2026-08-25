# Simulate a chopper cascade with `tof`

[`tof`](https://scipp.github.io/tof/) is a lightweight straight-line Monte Carlo from the
scipp developers, for chopper-cascade diagrams. It assumes neutrons travel in straight
lines and simulates neither absorption nor scattering — it will never replace McStas, and
it answers "what does my chopper train let through?" in a second rather than a coffee
break.

`niess.tof` builds a ready-to-run `tof.Model` from a niess instrument, so the train does
not have to be retyped.

```sh
pip install 'niess[tof]'
```

## Build a model

```python
--8<-- "tof_model.py:build"
```

```
TofSetup: 1 chopper(s), 2 detector(s)
  chopper  chopper                        14.000 Hz anticlockwise  1 opening(s) at   6.8100 m
  detector monitor
  detector sample_origin

  parameters used (override with with_values(...)):
    chopperspeed                 = 14.0 Hz  (default)  <- chopper.speed
    chopperdelay                 = 0.0 s  (default)  <- chopper.delay
  nothing has to be provided; every value came from the instrument itself.
```

Every monitor becomes a `tof.Detector`, and so does the sample — the places a cascade
diagram usually wants a curve. Distances are walked **along the beam**, following a curved
guide rather than cutting across it, and offset by the source's own distance because `tof`
measures every component from the same zero as its source.

## What you need to provide

Usually nothing, which is what the table says. niess declares each chopper's speed and
delay as an instrument parameter carrying the calibration's own value, so a model built
from a niess instrument is already the machine as calibrated.

The knobs are listed anyway, because knowing which ones exist is the point of asking, and
the report names *what read each one* — so a value that looks wrong can be traced to the
component that used it. Turn one with:

```python
--8<-- "tof_model.py:override"
```

`with_values` rebuilds from the same instrument, so the report then marks `chopperspeed` as
given rather than defaulted.

Anything the walk left out — a Fermi chopper, a disc whose description did not reduce to
numbers — is listed too, rather than quietly missing.

## Simulating more than one pulse

A chopper turning at a fraction of the source frequency does nothing visible in a single
pulse, because a single pulse is the one it lets through. `pulses=` runs several:

```python
setup = to_tof_model(assembler, pulses=2)
counts = setup.model.run().detectors['sample_origin'].toa.data
```

At ESS' 14 Hz, a bandwidth disc at 14 Hz opens once per pulse and passes them all, while
the same disc at 7 Hz opens for every other one and absorbs the rest — the second pulse
arrives at a closed disc and the count for it is zero. That is pulse skipping, and seeing
it is the reason to ask for more than one pulse.

`neutrons=` sets how many are sampled from each pulse, and `seed=` fixes the sampling so
two runs differ by what was changed rather than by which neutrons were drawn. Omitting
`pulses` takes the count from the source.

## Where the numbers come from

Off the discs themselves. A `DiscChopper` carries its speed, its delay and its window
edges as scipp quantities, so there is nothing to recover: `niess.tof` reads them and
converts. The beam-path walk it measures distances along is shared with `niess.chopcalc`
— both use `niess.chopcalc.paths` — so a chopper's distance is the same number in the
band calculation and in the diagram.

An instrument niess did *not* build has none of that, only emitted components. Modelling
one means `niess.tof.via_instr.to_tof_model`, which asks chopcalc for a train and parses
the numbers back out of the C it emits. It takes an `Assembler` rather than an
`Instrument`, and it is the older of the two routes.

The one thing that is not shared is the conversion into `tof`'s own description, because
the two disagree about how a chopper is specified:

| | niess | `tof` |
| --- | --- | --- |
| speed | signed, the sign is the direction | non-negative, direction is separate |
| timing | `delay`, in seconds | `phase`, an angle |
| angles | from the disc's zero mark | from the beam |

A delay is a *time*, so it delays the opening whichever way the disc turns, and the phase
angle it becomes — `360 · |speed| · delay` — carries **no** sign flip. A NeXus phase is an
angle in the disc's rotating frame and does flip, which is why `tof.Chopper.from_nexus`
negates it for a negative speed. Conflating the two is the inviting mistake, so the
conversion is pinned by checking `tof.Chopper.open_close_times()` against niess' own rule
for both directions on an asymmetric disc, where nothing lands back on itself.

## Staying offline

Building the source downloads a pulse profile on first use, cached afterwards. The profile
follows the instrument's own name — `bifrost` gets `ess-bifrost`, an instrument without one
falls back to `ess`. Pass your own source to avoid the download entirely:

```python
setup = to_tof_model(assembler, source=tof.Source.from_neutrons(...))
```

The instrument's `Lmin`/`Lmax` are then not consulted, and the report says so by not
listing them.
