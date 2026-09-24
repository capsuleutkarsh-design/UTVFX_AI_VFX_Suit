"""A strict stand-in for the parts of nuke.rotopaint the roto export uses.

It has only the methods and attributes Foundry documents (Nuke 14 Python API reference:
AnimCurve, AnimCurveKey, AnimControlPoint, ShapeControlPoint, AnimAttributes, Shape, Layer),
with __slots__, so a call real Nuke does not have fails here too. It also evaluates the
curves, so a test can check the shapes Nuke would draw on each frame.

`linear_sticks=False` makes setting a key's interpolation do nothing and interpolates
smoothly (Catmull-Rom) instead: the worst case for a script that assumes linear or step keys.
"""
import sys
import types

STEP, LINEAR, CUBIC = 0, 1, 2


class AnimCurveKey:
    __slots__ = ("time", "value", "interpolationType", "la", "ra", "lslope", "rslope", "_curve")

    def __init__(self, time, value, curve):
        self.time, self.value, self.la, self.ra, self.lslope, self.rslope = time, value, 0, 0, 0, 0
        self._curve = curve
        object.__setattr__(self, "interpolationType", CUBIC)

    def __setattr__(self, name, value):
        if name == "interpolationType" and not self._curve.linear_sticks:
            return
        object.__setattr__(self, name, value)


class AnimCurve:
    __slots__ = ("_keys", "_constant", "linear_sticks")

    def __init__(self, constant=0.0, linear_sticks=True):
        self._keys, self._constant, self.linear_sticks = [], constant, linear_sticks

    def addKey(self, time, value):
        self._keys = [k for k in self._keys if k.time != time] + [AnimCurveKey(time, value, self)]
        self._keys.sort(key=lambda k: k.time)

    def getNumberOfKeys(self):
        return len(self._keys)

    def getKey(self, index):
        return self._keys[index]

    def evaluate(self, t):
        keys = self._keys
        if not keys:
            return self._constant
        if t <= keys[0].time:
            return keys[0].value
        if t >= keys[-1].time:
            return keys[-1].value
        i = max(n for n, k in enumerate(keys) if k.time <= t)
        a, b = keys[i], keys[i + 1]
        u = (t - a.time) / (b.time - a.time)
        if a.interpolationType == STEP:
            return a.value
        if a.interpolationType == LINEAR:
            return a.value + u * (b.value - a.value)
        # Catmull-Rom through the neighbouring keys: smooth, and off the straight line.
        p0 = keys[i - 1].value if i > 0 else a.value
        p3 = keys[i + 2].value if i + 2 < len(keys) else b.value
        return 0.5 * (2 * a.value + (-p0 + b.value) * u + (2 * p0 - 5 * a.value + 4 * b.value - p3) * u * u
                      + (-p0 + 3 * a.value - 3 * b.value + p3) * u ** 3)


class AnimControlPoint:
    __slots__ = ("_curves",)

    def __init__(self, x=0.0, y=0.0, linear_sticks=True):
        self._curves = [AnimCurve(x, linear_sticks), AnimCurve(y, linear_sticks)]

    def getPositionAnimCurve(self, index):
        return self._curves[index]

    def addPositionKey(self, time, position):
        x, y = position
        self._curves[0].addKey(time, float(x))
        self._curves[1].addKey(time, float(y))

    def at(self, t):
        return self._curves[0].evaluate(t), self._curves[1].evaluate(t)


class ShapeControlPoint:
    __slots__ = ("center", "leftTangent", "rightTangent", "featherCenter", "featherLeftTangent", "featherRightTangent")
    linear_sticks = True

    def __init__(self, x, y):
        s = ShapeControlPoint.linear_sticks
        self.center = AnimControlPoint(x, y, s)
        for name in self.__slots__[1:]:
            setattr(self, name, AnimControlPoint(0.0, 0.0, s))


class AnimAttributes:
    __slots__ = ("_curves",)

    def __init__(self):
        self._curves = {}

    def set(self, *args):
        """set(name, value) sets a constant; set(time, name, value) adds a key (Nuke's two forms)."""
        if len(args) == 2:
            name, value = args
            self._curves[name] = AnimCurve(float(value))
        else:
            time, name, value = args
            self._curves.setdefault(name, AnimCurve(1.0, ShapeControlPoint.linear_sticks)).addKey(time, float(value))

    def getValue(self, time, name):
        return self._curves[name].evaluate(time) if name in self._curves else None

    def getCurve(self, name):
        return self._curves[name]


class Shape:
    __slots__ = ("name", "_points", "_attrs")

    def __init__(self, curves):
        self.name, self._points, self._attrs = "", [], AnimAttributes()

    def append(self, point):
        self._points.append(point)

    def __len__(self):
        return len(self._points)

    def __getitem__(self, i):
        return self._points[i]

    def getAttributes(self):
        return self._attrs


class Layer:
    __slots__ = ("name", "_items")

    def __init__(self, curves):
        self.name, self._items = "", []

    def append(self, item):
        self._items.append(item)

    def __iter__(self):
        return iter(self._items)

    def __len__(self):
        return len(self._items)


class Knob:
    __slots__ = ("value",)

    def __init__(self):
        self.value = None

    def setValue(self, v):
        self.value = v


class Curves:
    __slots__ = ("rootLayer", "changes")

    def __init__(self):
        self.rootLayer, self.changes = Layer(None), 0

    def changed(self):
        self.changes += 1


class Node:
    __slots__ = ("_knobs",)

    def __init__(self):
        self._knobs = {"curves": Curves(), "onCreate": Knob()}

    def __getitem__(self, name):
        return self._knobs[name]

    def knob(self, name):
        return self._knobs.get(name)


def install(monkeypatch, linear_sticks=True):
    """Put a fresh stand-in `nuke` and `nuke.rotopaint` in sys.modules; returns (node, messages)."""
    node, messages = Node(), []
    nuke = types.ModuleType("nuke")
    nuke.thisNode = lambda: node
    nuke.message = messages.append
    rp = types.ModuleType("nuke.rotopaint")
    rp.Layer, rp.Shape, rp.ShapeControlPoint = Layer, Shape, ShapeControlPoint
    rp.InterpolationType = types.SimpleNamespace(eStepInterpolationType=STEP, eLinearInterpolationType=LINEAR,
                                                 eCubicInterpolationType=CUBIC)
    nuke.rotopaint = rp
    ShapeControlPoint.linear_sticks = linear_sticks
    if monkeypatch is None:
        sys.modules["nuke"], sys.modules["nuke.rotopaint"] = nuke, rp
    else:
        monkeypatch.setitem(sys.modules, "nuke", nuke)
        monkeypatch.setitem(sys.modules, "nuke.rotopaint", rp)
    return node, messages


def shapes_of(node):
    """{"Layer/Shape": Shape} built on the node."""
    return {f"{layer.name}/{shape.name}": shape for layer in node["curves"].rootLayer for shape in layer}


def outline_at(shape, t):
    """[(x, y, left, right, feather, feather_left, feather_right)] of `shape` on frame t, absolute."""
    out = []
    for i in range(len(shape)):
        cv = shape[i]
        c = cv.center.at(t)
        l, r, fc = cv.leftTangent.at(t), cv.rightTangent.at(t), cv.featherCenter.at(t)
        f = (c[0] + fc[0], c[1] + fc[1])
        fl, fr = cv.featherLeftTangent.at(t), cv.featherRightTangent.at(t)
        out.append((c, (c[0] + l[0], c[1] + l[1]), (c[0] + r[0], c[1] + r[1]),
                    f, (f[0] + fl[0], f[1] + fl[1]), (f[0] + fr[0], f[1] + fr[1])))
    return out
