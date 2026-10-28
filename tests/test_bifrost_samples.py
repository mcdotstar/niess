"""Exchangeable simulated samples for BIFROST, from McStas' sample components.

What matters: every neutron goes to exactly one process with its weight corrected for the
choice, focusing processes aim at both the analyzers and the elastic monitor, and a data
file of one's own does not depend on where the simulation runs.
"""
import pytest

from niess.bifrost.samples import (
    Box, Cylinder, datafile, powder, sample, targets, tunneling, vanadium, spinwave,
)

ROD = Cylinder(radius=0.0015, height=0.02)


def test_targets_come_from_the_tank():
    analyzers, elastic = targets()
    assert (analyzers.angle, analyzers.width, analyzers.height) == (0.0, 90.0, 3.0)
    assert elastic.angle == 59.0
    # an inch-radius, 3.2 inch tube 800 mm away
    assert elastic.width == pytest.approx(3.637, abs=1e-3)
    assert elastic.height == pytest.approx(5.816, abs=1e-3)


def test_a_focusing_process_aims_at_both_targets_and_a_powder_at_neither():
    s = sample(powder('Al2O3_sapphire.laz', ROD, share=3), vanadium(ROD, share=1))
    by_name = {c.name: c for c in s.scatterers}
    assert list(by_name) == ['powder', 'vanadium_analyzers', 'vanadium_monitor']
    assert by_name['powder'].when == 'sample_switch == 0'
    assert by_name['vanadium_monitor'].when == 'sample_switch == 1 && detector_switch == 1'
    assert 'focus_aw' not in by_name['powder'].mccode_parameters
    monitor = by_name['vanadium_monitor'].mccode_parameters
    assert monitor['target_x'] == 'sin(DEG2RAD * (detector_tank_angle - sample_rotation + 59.0))'
    analyzers = by_name['vanadium_analyzers'].mccode_parameters
    assert analyzers['target_z'] == 'cos(DEG2RAD * (detector_tank_angle - sample_rotation))'
    # every scatterer stamps the time the readout measures from
    assert all(c.extend == 'event_time_zero = t;' for c in s.scatterers)


def test_shares_are_normalised_and_divided_out():
    extend = sample(powder('Al2O3_sapphire.laz', ROD, share=3), vanadium(ROD, share=1)).choice.extend
    assert 'sample_switch = (r < 0.75) ? 0 : 1;' in extend
    assert 'p /= (sample_switch == 0) ? 0.75 : 0.25;' in extend
    # only the focusing process pays for the target choice
    assert 'if (sample_switch == 1) p /=' in extend
    alone = sample(vanadium(ROD)).choice.extend
    assert 'sample_switch = 0;' in alone and 'p /= 1.0;' in alone


def test_the_shapes_say_the_same_to_mcstas_and_nexus():
    assert ROD.mccode() == {'radius': 0.0015, 'yheight': 0.02}
    assert ROD.nexus()['radius'] == (0.0015, 'm')
    box = Box(width=0.005, height=0.005, depth=0.005)
    assert box.mccode() == {'xwidth': 0.005, 'yheight': 0.005, 'zdepth': 0.005}
    assert box.nexus()['size'] == ([0.005, 0.005, 0.005], 'm')


def test_own_data_files_are_absolute_and_shipped_ones_bare(tmp_path, monkeypatch):
    mine = tmp_path / 'mine.laz'
    mine.write_text('')
    monkeypatch.chdir(tmp_path)
    from pathlib import Path
    assert datafile(Path('mine.laz')) == f'"{mine}"'
    assert datafile('Al2O3_sapphire.laz') == '"Al2O3_sapphire.laz"'
    with pytest.raises(ValueError, match='pathlib.Path'):
        datafile('data/mine.laz')
    with pytest.raises(FileNotFoundError):
        datafile(tmp_path / 'missing.laz')


def test_bad_samples_are_refused():
    with pytest.raises(ValueError):
        sample()
    with pytest.raises(ValueError, match='differ'):
        sample(vanadium(ROD), vanadium(ROD))
    with pytest.raises(ValueError, match='positive'):
        sample(vanadium(ROD, share=0))
    with pytest.raises(ValueError, match='solid cylinder'):
        spinwave(Box(width=0.01, height=0.01, depth=0.01))


def test_it_sits_on_bifrosts_sample_table():
    from niess.bifrost.bifrost import instrument
    from niess.mccode import to_mccode
    s = sample(tunneling(ROD, E_tun=0.032, share=0.8), vanadium(ROD, share=0.2))
    instr = to_mccode(instrument(sample=s))
    names = [c.name for c in instr.components]
    at = names.index('sample_choice')
    assert names[at:at + 5] == ['sample_choice', 'tunneling_analyzers', 'tunneling_monitor',
                                'vanadium_analyzers', 'vanadium_monitor']
    # after the split, so a sample change keeps restage's cached primary
    assert names.index('split_before_sample') < at
    assert any('int sample_switch;' in u.source for u in instr.user)


def test_a_remounted_sample_sits_at_its_offset_on_the_stack():
    from niess.bifrost.bifrost import instrument
    from niess.mccode import to_mccode
    s = sample(powder('Al2O3_sapphire.laz', ROD), offset=(0, 0.002, -0.001))
    assert list(s.scatterers[0].position.value) == [0.0, 0.002, -0.001]
    # the choice stays at the sample position, and the rest of BIFROST is unmoved
    assert list(s.choice.position.value) == [0.0, 0.0, 0.0]
    powder_at = {c.name: c for c in to_mccode(instrument(sample=s)).components}['powder'].at_relative
    assert [float(str(v)) for v in powder_at[0]] == [0.0, 0.002, -0.001]
    with pytest.raises(ValueError, match='offset'):
        sample(vanadium(ROD), offset=(0, 0.002))
