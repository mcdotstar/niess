"""Regression tests run on Linux only, unless asked for.

A *regression* test compares what niess builds against a file frozen from an earlier build
(``tests/data/baseline``). The files hold thousands of floats written at full precision --
positions and rotations worked out through scipp and numpy -- and they are compared
exactly, because a tolerance wide enough to absorb a platform would also absorb a real
change the size of one.

They were minted on Linux. Another operating system, or another CPU, is free to round the
last bit of a computed rotation differently and still be right, and an exact comparison
cannot tell that from a regression (#103). So these run where the files were made, and
are skipped elsewhere; every other test runs everywhere.

Mark a test ``@pytest.mark.regression`` when it compares floating-point results against a
frozen file. A frozen comparison with no floats in it -- a flow graph, a field order, a
count -- is platform independent and should stay unmarked, so it keeps running on every
platform. ``pytest --regression`` runs the marked tests anyway, which is how to see what
actually differs on a new platform.
"""
import sys

import pytest

#: Where the frozen files were minted, and so where an exact comparison means something.
REGRESSION_PLATFORM = 'linux'


def pytest_addoption(parser):
    parser.addoption(
        '--regression', action='store_true', default=False,
        help=f'run the regression tests on {sys.platform}, not only on '
             f'{REGRESSION_PLATFORM}, where their frozen files were minted',
    )


def pytest_collection_modifyitems(config, items):
    if sys.platform == REGRESSION_PLATFORM or config.getoption('--regression'):
        return
    skip = pytest.mark.skip(
        reason=f'regression test: frozen on {REGRESSION_PLATFORM}, so an exact float '
               f'comparison is not meaningful on {sys.platform}; pass --regression to '
               f'run it anyway'
    )
    for item in items:
        if 'regression' in item.keywords:
            item.add_marker(skip)
