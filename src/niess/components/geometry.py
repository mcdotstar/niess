import msgspec
from scipp import Variable


def one_of(params: dict[str, Variable], names: list[str], fallback: Variable):
    for name in names:
        if name in params:
            return params[name]
    return fallback


def any_perpendicular(v: Variable):
    from scipp import vector, dot, cross, norm, abs
    x, y, z = vector([1., 0, 0]), vector([0, 1., 0]), vector([0, 0, 1.])
    lv = norm(v, v)
    if abs(d := dot(x, v)) < lv:
        p = x - d / lv * x
    elif abs(d := dot(y, v)) < lv:
        p = y - d / lv * y
    elif abs(d := dot(z, v)) < lv:
        p = z - d / lv * z
    else:
        raise ValueError(f'No perpendicular vector to {v} with length {lv}')
    if dot(p, v) > 0. * lv:
        raise ValueError(f'{p} not perpendicular to {v} with length {lv}')
    return p


class Off(msgspec.Struct):
    vertices: tuple[tuple[float, float, float], ...]
    faces: tuple[tuple[int, ...], ...]

    @classmethod
    def hollow_wedge(cls, params: dict[str, Variable]):
        from scipp import scalar

        w1 = one_of(params,['w1', 'width', 'width_in'], scalar(0., unit='m'))
        w2 = one_of(params,['w2', 'width_out'], w1)
        h1 = one_of(params,['h1', 'height', 'height_in'], scalar(0., unit='m'))
        h2 = one_of(params,['h2', 'height_out'], h1)
        l = one_of(params, ['length', 'len', 'l', 'L'], scalar(0., unit='m'))
        x1, y1, x2, y2 = (float(n.to(unit='m').value)/2 for n in (w1, h1, w2, h2))
        l = float(l.to(unit='m').value)

        # close vertices first: (bottom right, top right, top left, bottom left)
        # then the same but farther away
        vertices = [
            [-x1, -y1, 0.], [-x1, y1, 0.], [x1, y1, 0.], [x1, -y1, 0.],
            [-x2, -y2, l], [-x2, y2, l], [x2, y2, l], [x2, -y2, l],
        ]
        # Clockwise winding, facing out -- no front or back faces!
        faces = [
            [1, 5, 6, 2], # top right, far top right, far top left, top left == top
            [1, 0, 4, 5], # top right, bottom right, far bottom right, far top right == right
            [7, 4, 0, 3], # far bottom left, far bottom right, bottom right, bottom left == bottom
            [6, 7, 3, 2], # far top left, far bottom left, bottom left, top left == left
        ]
        return cls(
            vertices=tuple([tuple(p) for p in vertices]),
            faces=tuple([tuple(f) for f in faces]),
        )

    @classmethod
    def elliptic_channel(cls, rings: list[tuple[float, float, float]]):
        """The inside of a guide whose cross-section varies along its length.

        ``rings`` is (half-width, half-height, z) for each cross-section, in metres and
        in order. Consecutive rings are joined by four quads, so a guide given n+1 rings
        has 4n faces -- and, like :meth:`hollow_wedge`, no entry or exit face, because a
        guide is a channel and not a box.

        Faces come out in the same [top, right, bottom, left] order per segment that
        :meth:`hollow_wedge` uses, so one m-value list indexes either.
        """
        vertices, faces = [], []
        for half_width, half_height, z in rings:
            x, y = float(half_width), float(half_height)
            # matching hollow_wedge: (bottom right, top right, top left, bottom left)
            vertices.extend([[-x, -y, float(z)], [-x, y, float(z)],
                             [x, y, float(z)], [x, -y, float(z)]])
        for segment in range(len(rings) - 1):
            n0, n1, n2, n3, f0, f1, f2, f3 = (4 * segment + k for k in range(8))
            faces.extend([
                [n1, f1, f2, n2],  # top
                [n1, n0, f0, f1],  # right
                [f3, f0, n0, n3],  # bottom
                [f2, f3, n3, n2],  # left
            ])
        return cls(
            vertices=tuple(tuple(v) for v in vertices),
            faces=tuple(tuple(f) for f in faces),
        )

    def to_nexus(self, name: str | None = None) -> dict:
        from numpy import cumsum
        from ..nexus.nodes import group, dataset
        if name is None:
            name = 'geometry'
        winding_order = [index for face in self.faces for index in face]
        face_offsets = [0] + cumsum([len(f) for f in self.faces[:-1]]).tolist()
        vertices = [[float(v) for v in vertex] for vertex in self.vertices]
        return group(
            name, 'NXoff_geometry', children=[
                dataset('vertices', vertices, dtype='double', attrs={'units': 'm'}),
                dataset('winding_order', [int(w) for w in winding_order], dtype='int64'),
                dataset('faces', [int(f) for f in face_offsets], dtype='int64'),
            ]
        )


class Cylinder(msgspec.Struct):
    vertices: tuple[tuple[float, float, float], ...]
    cylinders: tuple[tuple[int, int, int], ...]

    @classmethod
    def single(cls, params: dict[str, Variable]):
        from scipp import vector
        from ..spatial import __is_vector__
        c = one_of(params, ['center', 'at'], vector([0, 0, 0], unit='m'))
        l = one_of(params, ['length', 'len', 'l', 'L'], vector([0, 1, 0], unit='m'))
        r = one_of(params, ['radius', 'radius', 'r', 'R'], vector([0, 0, 0], unit='m'))
        if not __is_vector__(r):
            r = r * any_perpendicular(l)

        vertices = tuple([
            tuple([float(v) for v in vertex.to(unit='m').value])
            for vertex in [c - l/2, c -l/2 + r, c + l/2]
        ])
        return cls(vertices=vertices, cylinders=((0, 1, 2),),)


    def to_nexus(self, name: str | None = None) -> dict:
        from ..nexus.nodes import group, dataset
        if name is None:
            name = 'geometry'
        vertices = [[float(v) for v in vertex] for vertex in self.vertices]
        cylinders = [[int(c) for c in cylinder] for cylinder in self.cylinders]
        return group(
            name, 'NXcylindrical_geometry', children=[
                dataset('vertices', vertices, dtype='double', attrs={'units': 'm'}),
                dataset('cylinders', cylinders, dtype='int64'),
            ]
        )