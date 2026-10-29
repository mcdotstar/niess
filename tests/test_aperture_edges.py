"""Which side of the beam an aperture's ``left`` edge is on.

ESS's: McStas and NeXus put +x on the left looking downstream, and ECDC binds every
``left`` edge to an ``SlYp`` (+Y) motor, PV Y being NeXus x. So ``left`` is the edge at
+x, McStas ``xmax``, and an open, centred jaw has it positive.
"""
import scipp as sc


def _slit():
    from niess.components import Slit
    return Slit(name='slit', position=sc.vector([0.0, 0.0, 0.0], unit='m'),
                orientation=sc.spatial.rotation(value=[0.0, 0.0, 0.0, 1.0]),
                width=sc.scalar(0.05, unit='m'), height=sc.scalar(0.03, unit='m'))


def test_left_is_the_edge_at_plus_x():
    slit = _slit()
    _, params = slit.__mccode__()
    assert params['xmax'] == '0.001 * slit_left'
    assert params['xmin'] == '0.001 * slit_right'
    assert params['ymax'] == '0.001 * slit_top'
    assert params['ymin'] == '0.001 * slit_bottom'


def test_an_open_slit_has_left_and_top_positive():
    defaults = {edge: p.value for edge, p in _slit().edge_parameters().items()}
    assert defaults == {'left': 25.0, 'right': -25.0, 'bottom': -15.0, 'top': 15.0}


def test_ecdc_binds_every_left_edge_to_a_plus_y_motor():
    from niess.bifrost.ecdc import bindings
    sides = {'left': ':MC-SlYp-', 'right': ':MC-SlYm-'}
    checked = 0
    for key, binding in bindings().items():
        for edge, motor in sides.items():
            if f'.{edge}.' in key:
                assert motor in binding.source, key
                checked += 1
    assert checked > 0
