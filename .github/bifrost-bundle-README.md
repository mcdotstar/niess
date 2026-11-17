# BIFROST McStas bundle

The BIFROST model as a McStas instrument, generated from
[niess](https://github.com/mcdotstar/niess) and attached to each niess release.

## Running it

    mcrun -c -n 1e6 -d run bifrost.instr sample_rotation=30 detector_tank_angle=-5

`bifrost.instr` declares every instrument parameter; `mcrun bifrost.instr --info` lists
them. Units are the ones the real instrument logs (chopper delays in ns, jaws in mm), so a
value read from a data file can be passed straight in.

This directory holds the instrument files and the components and C libraries that do not
ship with McStas. Standard components (`Arm`, `Slit`, `Guide_gravity`, ...) come from
your McStas installation.

## Where the model lives

niess is the only source of the BIFROST model; this bundle is generated from it. The
same niess objects also produce the NeXus file structure, the detector calibration and
the chopper phasing, so a correction made only here reaches none of those.

- **Changing a parameter** (chopper speed or phase, slit openings, sample and detector
  tank angles): set it on the `mcrun` command line. Nothing needs editing.
- **Your own study** (an extra monitor, a different sample): edit your copy. It is yours.
- **Correcting the model** (a position, a dimension, a coating): keep this bundle
  unmodified, make the change in a copy, run `diff -ru bifrost/ my-bifrost/ > change.diff`,
  and open an issue on https://github.com/mcdotstar/niess with the diff and why. The
  change is made in niess and appears in the next bundle. To make the change in niess
  yourself, see https://mcdotstar.github.io/niess/how-to/change-bifrost/

Each `.instr` file's header names the niess and mccode-antlr versions that wrote it and
the release of each component repository the bundled components came from.
