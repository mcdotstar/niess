"""The OFF geometry a guide writes is the channel the component actually traces.

These came out of porting moreniius' geometry across. Its wedge was right; its ellipse
was not, and the error was the kind that survives inspection -- the shape stays a
plausible guide, it is just the wrong one. So the width is checked against the
expression the component evaluates rather than against the code it was ported from.
"""
from math import sqrt

import pytest

from niess.components.guide import EllipticGuide, StraightGuide, TaperedGuide


#: face order per segment, as `Off.hollow_wedge` and `Off.elliptic_channel` wind them:
#: (name, vertex axis, the sign every vertex of that face must have on it)
FACES = [('top', 1, +1), ('right', 0, -1), ('bottom', 1, -1), ('left', 0, +1)]


@pytest.fixture(scope='module')
def guides():
    from niess.bifrost import Primary
    from niess.bifrost.parameters import primary_parameters
    from niess.tree import leaves
    from niess.components.guide import Guide
    primary = Primary.from_calibration(primary_parameters())
    return [node for _, node in leaves(primary) if isinstance(node, Guide)]


def test_bifrost_has_both_kinds(guides):
    """So the checks below are not quietly passing over an empty list."""
    kinds = {type(g).__name__ for g in guides}
    assert kinds == {'StraightGuide', 'EllipticGuide'}
    assert len(guides) == 119


def test_every_face_lies_on_the_side_its_m_value_names(guides):
    """The m-values index the faces positionally, so a mismatch mislabels a mirror.

    Which is a thing no reader can detect: the file stays well-formed and the guide
    stays a guide, it just says the coating on the top is the coating on the left.
    """
    checked = 0
    for guide in guides:
        off = guide.__off__()
        assert off is not None, guide.name
        for index, face in enumerate(off.faces):
            side, axis, sign = FACES[index % 4]
            vertices = [off.vertices[v] for v in face]
            assert all(sign * v[axis] >= 0 for v in vertices), f'{guide.name} {side}'
            # a side face spans exactly two cross-sections
            assert len({round(v[2], 12) for v in vertices}) == 2, f'{guide.name} {side}'
            checked += 1
    assert checked == 1512


def test_there_is_one_m_value_per_face(guides):
    for guide in guides:
        segments = len(guide.__off__().faces) // 4
        assert len(guide.__m_values__(segments)) == len(guide.__off__().faces), guide.name


def test_a_guide_is_a_channel_and_not_a_box(guides):
    """No entry or exit face: a neutron goes in one end and out the other."""
    for guide in guides:
        off = guide.__off__()
        for face in off.faces:
            zs = {round(off.vertices[v][2], 12) for v in face}
            assert len(zs) == 2, f'{guide.name} has a face at one z, which caps it'


def test_the_elliptic_width_is_the_one_the_component_traces(guides):
    """Against Elliptic_guide_gravity.comp:483, not against what it was ported from.

    The component computes the full width at z as

        2 * sqrt(1 - (z - majorAxisoffset)^2 / majorAxis^2) * minorAxis

    moreniius used `offset - minor + z` where this needs `z - offset`: a sign on the
    offset, and a spurious minor. Both are small next to the major axis, so the shape
    stayed guide-like -- but the widest point of the channel sits at `z == offset`, and
    getting the sign wrong puts it at `-offset`, which for BIFROST's guides is usually
    outside the guide altogether. The worst face was out by 100%.
    """
    for guide in guides:
        if not isinstance(guide, EllipticGuide):
            continue
        off = guide.__off__()
        for ring, z in enumerate(guide.__ring_positions__()):
            # the ring's four vertices are (-w,-h), (-w,h), (w,h), (w,-h)
            half_width = abs(off.vertices[4 * ring][0])
            half_height = abs(off.vertices[4 * ring][1])
            for ellipse, got in ((guide.horizontal, half_width),
                                 (guide.vertical, half_height)):
                major = float(ellipse.major.to(unit='m').value)
                minor = float(ellipse.minor.to(unit='m').value)
                offset = float(ellipse.offset.to(unit='m').value)
                along = z - offset
                want = (minor * sqrt(1 - (along / major) ** 2)
                        if abs(along) < abs(major) else 0.0)
                assert got == pytest.approx(want, abs=1e-15), f'{guide.name} ring {ring}'


def test_a_segmented_guide_rings_at_its_segment_boundaries(guides):
    """Because each segment has its own coating, and a ring inside one could not say so."""
    from scipp import sum as ssum
    segmented = [g for g in guides
                 if isinstance(g, EllipticGuide) and isinstance(g.left, tuple)]
    assert segmented, 'BIFROST has guides with a per-segment m-value'
    for guide in segmented:
        rings = guide.__ring_positions__()
        assert len(rings) == len(guide.left) + 1
        assert rings[0] == 0.0
        assert rings[-1] == pytest.approx(float(ssum(guide.length).to(unit='m').value))
        # each face gets the coating of the segment it belongs to
        m_values = guide.__m_values__(len(rings) - 1)
        for segment in range(len(rings) - 1):
            assert m_values[4 * segment] == float(guide.top[segment])
            assert m_values[4 * segment + 1] == float(guide.right[segment])


def test_a_plain_elliptic_guide_is_drawn_with_ten_segments(guides):
    plain = [g for g in guides
             if isinstance(g, EllipticGuide) and not isinstance(g.left, tuple)]
    assert plain
    for guide in plain:
        assert len(guide.__ring_positions__()) == EllipticGuide.OFF_SEGMENTS + 1
        assert len(guide.__off__().faces) == 4 * EllipticGuide.OFF_SEGMENTS


def test_a_tapered_guide_is_one_wedge_between_its_two_ends():
    """It has no `__off__` of its own beyond the wedge, but its ends differ."""
    import scipp as sc
    from scipp.spatial import rotations_from_rotvecs as r
    guide = TaperedGuide(
        name='t', position=sc.vector([0, 0, 0.], unit='m'),
        orientation=r(sc.vector([0, 0, 0.], unit='deg')),
        length=sc.scalar(2.0, unit='m'), left=1., right=2., top=3., bottom=4.,
        in_width=sc.scalar(0.10, unit='m'), out_width=sc.scalar(0.04, unit='m'),
        in_height=sc.scalar(0.20, unit='m'), out_height=sc.scalar(0.08, unit='m'),
    )
    off = guide.__off__()
    assert len(off.vertices) == 8 and len(off.faces) == 4
    assert off.vertices[0] == (-0.05, -0.10, 0.0), 'the entrance is half the in size'
    assert off.vertices[4] == (-0.02, -0.04, 2.0), 'the exit is half the out size'
    assert guide.__m_values__() == [3.0, 2.0, 4.0, 1.0], 'top, right, bottom, left'


def test_a_straight_guide_does_not_taper():
    import scipp as sc
    from scipp.spatial import rotations_from_rotvecs as r
    guide = StraightGuide(
        name='s', position=sc.vector([0, 0, 0.], unit='m'),
        orientation=r(sc.vector([0, 0, 0.], unit='deg')),
        length=sc.scalar(1.0, unit='m'), left=2., right=2., top=2., bottom=2.,
        width=sc.scalar(0.04, unit='m'), height=sc.scalar(0.06, unit='m'),
    )
    off = guide.__off__()
    near = {(v[0], v[1]) for v in off.vertices if v[2] == 0.0}
    far = {(v[0], v[1]) for v in off.vertices if v[2] == 1.0}
    assert near == far
