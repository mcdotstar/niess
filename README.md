# niess

[![PyPI - Version](https://img.shields.io/pypi/v/niess.svg)](https://pypi.org/project/niess)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/niess.svg)](https://pypi.org/project/niess)

-----

## Table of Contents

- [Installation](#installation)
- [License](#license)
- [Motivation](#motivation)
- [Use](#use)

## Installation

```console
pip install niess
```

## License

`niess` is distributed under the terms of the [BSD-3-Clause](https://spdx.org/licenses/BSD-3-Clause.html) license.

## Motivation
This package is intended to hold information about the **N**eutron **I**nsruments
of the **E**uropean **S**pallation **S**ource for use in defining Monte Carlo 
ray-tracing simulations, file-layout information for use by the ESS
file-writers, and other yet-undefined uses; in a use-agnostic approach.

The information required about an instrument for `McStas` and `NeXusStructure` is
similar but not identical -- the latter attempts to hold all information needed to
produce a valid `NeXus` file, which requires geometry information _inspired_ by the
`McCode` implementation used by `McStas`.

The two uses each have their own vocabulary, and the vocabulary used here is more
closely in line with that of `McCode`. The basic building block of the two uses
is the `Comp` in `McCode` and the `NXclass` in `NeXus`; here the term 'component' is
used to refer to such a building block.
Since there are sometimes slight differences between the 'same' `Comp` and `NXclass` 
in how equivalent information is stored, `niess` is intended to be component-aware as
a single translation between the two is not possible globally.

Rather than attempting to store one implementation or the other, `niess` components
are an independent low-level representation of the properties of a component.
This representation can be written as a dictionary with pre-defined keys, and 
it is intended that serializing to and deserializing from such a representation can be 
used to provide calibrated instrument information to `McStas` and `NeXusStructure`.


## Use
Thus far only as-designed information is provided for the BIFROST indirect geometry
multiplexing spectrometer. You can load this information in a Python script, and use
them to define a `niess` representation of the primary and secondary spectrometers

```python
from niess.bifrost.parameters import primary_parameters, known_channel_params
from niess.bifrost import Primary, Tank
primary = Primary.from_calibration(primary_parameters())
secondary = Tank.from_calibration(known_channel_params())
```

The primary spectrometer begins at the source, here located at the nominal
position of the viewed moderator in the Instrument Specific Coordinate System (ISCS),
and ends with the position of the sample in the same coordinate system.

The secondary spectrometer is defined in a coordinate system relative to the sample position.

It is possible to convert the `niess` representations of these instrument parts to
their `McCode` representation and insert them into a `McStas` instrument by leveraging
an `Assembler` from the `mccode_antlr` package.

```python
from mccode_antlr import Flavor
from mccode_antlr.assembler import Assembler
from mccode_antlr.reader import GitHubRegistry
from niess.bifrost.parameters import primary_parameters, tank_parameters
from niess.bifrost import Primary, Tank

registries = ['mcstas-chopper-lib', 'mcstas-transformer', 'mcstas-detector-tubes',
              'mcstas-epics-link', 'mcstas-frame-tof-monitor', 'mccode-mcpl-filter',
              'mcstas-monochromator-rowland', 'mcstas-slit-radial']
registries = [GitHubRegistry(
    name,
    url=f'https://github.com/mcdotstar/{name}',
    filename='pooch-registry.txt',
    version='main'
) for name in registries]


assembler = Assembler('bifrost', registries=registries, flavor=Flavor.MCSTAS)
Primary.from_calibration(primary_parameters()).to_mccode(assembler)
Tank.from_calibration(tank_parameters()).to_mccode(assembler, 'sample_coordinates')

```