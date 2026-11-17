"""The .instr bundle niess publishes compiles and runs with a stock McStas.

The route people without Python take: save the instrument, `mccode-antlr extract` it
with every remote file except McStas's own library, then `mcrun` it. Skipped unless
`mcrun` is on PATH; the stock-mcstas CI job installs it from conda-forge.

A short run is enough: besides compiling, it runs every component's INITIALIZE, which is
where e.g. Detector_tubes exits if a particle variable it writes is undeclared.
"""
import shutil
import subprocess
import sys

import pytest


@pytest.mark.skipif(shutil.which('mcrun') is None, reason='needs a stock McStas (mcrun) on PATH')
def test_bifrost_bundle_runs_with_stock_mcstas(tmp_path):
    from mccode_antlr.io.json import save_json
    from niess.bifrost.bifrost import instrument
    from niess.mccode import to_mccode

    save_json(to_mccode(instrument()), tmp_path / 'bifrost.json')
    bundle = tmp_path / 'bundle'
    subprocess.run(
        [sys.executable, '-m', 'mccode_antlr.cli.management', 'extract', 'bifrost.json',
         '--include-remote', '-X', '*/mccode-dev/McCode', '-o', str(bundle)],
        cwd=tmp_path, check=True,
    )
    assert not (bundle / 'Arm.comp').exists(), 'the stock library should not be bundled'

    run = subprocess.run(
        ['mcrun', '-c', '-y', '-n', '1000', '-d', 'run', 'bifrost.instr'],
        cwd=bundle, capture_output=True, text=True,
    )
    assert run.returncode == 0, run.stdout[-4000:] + run.stderr[-4000:]
