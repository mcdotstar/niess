# niess

[![PyPI - Version](https://img.shields.io/pypi/v/niess.svg)](https://pypi.org/project/niess)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/niess.svg)](https://pypi.org/project/niess)

-----

## Table of Contents

- [Installation](#installation)
- [Documentation](https://mcdotstar.github.io/niess/)
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

`niess` describes an instrument once, as calibration data, and emits it as a McStas
instrument, ESS NeXus Structure JSON, or CAD geometry:

```python
from niess.bifrost import Primary, Tank
from niess.bifrost.parameters import primary_parameters, tank_parameters
from niess.instrument import Instrument, Mount
from niess.nexus import to_nexus_structure
from niess.nexus.bifrost import BIFROST_REGISTRY

bifrost = Instrument(name='bifrost', origin='sample_origin', parts=(
    Mount(name='primary', content=Primary.from_calibration(primary_parameters())),
    Mount(name='tank', content=Tank.from_calibration(tank_parameters()),
          relative_to='sample_origin'),
))

structure = to_nexus_structure(bifrost, registry=BIFROST_REGISTRY)
```

Full documentation, including how to translate an existing McStas `.instr` into a
`niess` submodule and how to write your own NeXus translators, is at
**<https://mcdotstar.github.io/niess/>**.

- [Install and first instrument](https://mcdotstar.github.io/niess/getting-started/)
- [Translate a McStas .instr](https://mcdotstar.github.io/niess/how-to/translate-an-instr/)
- [Build a new instrument submodule](https://mcdotstar.github.io/niess/how-to/new-instrument-submodule/)
- [Produce NeXus Structure JSON](https://mcdotstar.github.io/niess/how-to/nexus-structure/)
