"""The wiring diagram: DAQ terminals in the middle, the devices beside them."""

from collections import defaultdict

from pyqtgraph.Qt import QtCore, QtGui, QtWidgets

from acq4_tools.tools.rig_analysis import Connection, RigAnalysis, board_for

TERMINAL_WIDTH = 170
DEVICE_WIDTH = 300
GAP = 280
ROW = 24
HEADER = 28
DEVICE_SPACING = 14
SOURCE_GAP = 14
BOARD_SPACING = 40
# About a landscape page at the width of a diagram with devices on one side.
MAX_ONE_SIDE_HEIGHT = 560

# Chosen to stay distinct from each other and from PROBLEM under simulated
# protan, deutan and tritan color vision. Analog is blue, digital is purple.
KIND_COLORS = {
    "ai": "#1105BD", "ao": "#2C8496", "di": "#711174", "do": "#D806F9", "trigger": "#222222",
}
KIND_LABELS = (("ai", "analog in"), ("ao", "analog out"), ("di", "digital in"),
               ("do", "digital out"), ("trigger", "trigger"))
INPUT_KINDS = ("ai", "di", "trigger")
PROBLEM = "#C00000"
MUTED = "#999999"
TEXT = "#000000"
UNKNOWN_KIND = "#333333"
# In units of the pen width. Solid, dashed, dash-dot and dash-double-dot.
LINE_PATTERNS = ((), (7, 3), (9, 3, 2.5, 3), (9, 3, 2.5, 3, 2.5, 3))
PEN_WIDTH = 1.8
# Header color and body tint for each board, so that boards are told apart at a glance.
BOARD_STYLES = (("#1F3A5F", "#F2F5F9"), ("#7A4B00", "#FBF3E4"), ("#4A4A4A", "#EFEFEF"))


def left_side_devices(by_device: dict, users: dict) -> set:
    """Devices that can sit left of the DAQ without any of their wires crossing:
    none of their terminals is shared, and all of them are on one board."""
    chosen = set()
    for name, connections in by_device.items():
        boards = {(c.daq, c.terminal.dev) for c in connections}
        if len(boards) == 1 and all(len(users[c.daq, c.terminal]) == 1 for c in connections):
            chosen.add(name)
    return chosen


def stack_height(by_device: dict) -> float:
    return sum(HEADER + ROW * len(connections) + DEVICE_SPACING
               for connections in by_device.values())


def terminal_order(terminals: list, owners: dict) -> list:
    """Sort terminals, keeping those of each left-side device next to each other."""
    ordered = sorted(terminals, key=lambda t: t.sort_key)
    result: list = []
    for terminal in ordered:
        if terminal in result:
            continue
        owner = owners.get(terminal)
        result.extend([t for t in ordered if owners.get(t) == owner] if owner else [terminal])
    return result


class WiringDiagram:
    def __init__(self, scene: QtWidgets.QGraphicsScene):
        self.scene = scene
        self.items: list = []
        self.bounds = QtCore.QRectF()

    def clear(self) -> None:
        for item in self.items:
            self.scene.removeItem(item)
        self.items = []
        self.bounds = QtCore.QRectF()

    def _add(self, item):
        self.scene.addItem(item)
        self.items.append(item)
        self.bounds = self.bounds.united(item.sceneBoundingRect())
        return item

    def _text(self, text: str, x: float, y: float, color: str = TEXT, bold: bool = False,
              align: str = "left"):
        item = QtWidgets.QGraphicsSimpleTextItem(text)
        font = item.font()
        font.setPointSize(10)
        font.setBold(bold)
        item.setFont(font)
        item.setBrush(QtGui.QBrush(QtGui.QColor(color)))
        width = item.boundingRect().width()
        offset = {"left": 0.0, "center": width / 2, "right": width}[align]
        item.setPos(x - offset, y - item.boundingRect().height() / 2)
        return self._add(item)

    def _box(self, x: float, y: float, width: float, height: float, muted: bool = False):
        item = QtWidgets.QGraphicsRectItem(x, y, width, height)
        pen = QtGui.QPen(QtGui.QColor(MUTED if muted else "#333333"))
        if muted:
            pen.setDashPattern([7, 3])
        item.setPen(pen)
        item.setBrush(QtGui.QBrush(QtGui.QColor("#F7F7F7")))
        return self._add(item)

    def _wire(self, daq_point: QtCore.QPointF, device_point: QtCore.QPointF,
              connection: Connection, style: int) -> None:
        color = QtGui.QColor(MUTED if not connection.active
                             else KIND_COLORS.get(connection.kind, UNKNOWN_KIND))
        path = QtGui.QPainterPath(daq_point)
        middle = (daq_point.x() + device_point.x()) / 2
        path.cubicTo(QtCore.QPointF(middle, daq_point.y()),
                     QtCore.QPointF(middle, device_point.y()), device_point)
        pen = QtGui.QPen(color, PEN_WIDTH)
        pattern = LINE_PATTERNS[style % len(LINE_PATTERNS)]
        if pattern:
            pen.setDashPattern(list(pattern))
        wire = QtWidgets.QGraphicsPathItem(path)
        wire.setPen(pen)
        self._add(wire)
        tip, other = daq_point, device_point
        if connection.kind not in INPUT_KINDS:
            tip, other = device_point, daq_point
        direction = 1 if other.x() > tip.x() else -1
        head = QtWidgets.QGraphicsPolygonItem(QtGui.QPolygonF([
            tip,
            QtCore.QPointF(tip.x() + direction * 9, tip.y() - 4),
            QtCore.QPointF(tip.x() + direction * 9, tip.y() + 4),
        ]))
        head.setPen(QtGui.QPen(color))
        head.setBrush(QtGui.QBrush(color))
        self._add(head)

    def _legend(self) -> None:
        x = 0.0
        for kind, label in KIND_LABELS:
            self._text(f"■ {label}", x, -44, KIND_COLORS[kind])
            x += 105
        self._text("Red port: shared and not marked as alternates.", x + 10, -44, PROBLEM)
        self._text("Line style separates the devices that share a terminal.", 0, -24)

    # ------------------------------------------------------------------
    # layout
    # ------------------------------------------------------------------
    def draw(self, analysis: RigAnalysis, include_commented: bool) -> None:
        self.clear()
        self._legend()
        shown = [c for c in analysis.connections if c.active or include_commented]
        if not shown:
            self._text("No DAQ connections to show.", 0, 20)
            return
        users: dict = defaultdict(list)
        by_device: dict = {}
        for connection in shown:
            users[connection.daq, connection.terminal].append(connection)
            by_device.setdefault(connection.device, []).append(connection)
        styles = {}
        for connections in users.values():
            connections.sort(key=lambda c: (not c.active, c.device, c.port))
            for index, connection in enumerate(connections):
                styles[id(connection)] = index

        left: set = set()
        if stack_height(by_device) > MAX_ONE_SIDE_HEIGHT:
            left = left_side_devices(by_device, users)
        daq_x = float(DEVICE_WIDTH + GAP) if left else 0.0
        terminal_y = self._draw_boards(analysis, shown, users, left, daq_x)

        problems = {(s.daq, s.terminal) for s in analysis.shared if not s.marked}
        boards = {(c.daq, c.terminal.dev) for c in shown}
        names = {name: by_device[name] for name in left}
        if names:
            self._draw_side(names, terminal_y, styles, problems, boards, users, 0.0, daq_x,
                            "left")
        names = {name: value for name, value in by_device.items() if name not in left}
        if names:
            edge = daq_x + TERMINAL_WIDTH
            self._draw_side(names, terminal_y, styles, problems, boards, users, edge + GAP, edge,
                            "right")

    def _draw_boards(self, analysis: RigAnalysis, shown: list, users: dict, left: set,
                     x: float) -> dict:
        """Draw a box for each DAQ board. Returns the height of each terminal."""
        terminal_y: dict = {}
        owners = {(c.daq, c.terminal): c.device for c in shown if c.device in left}
        y = 0.0
        for number, (daq, dev) in enumerate(sorted({(c.daq, c.terminal.dev) for c in shown})):
            accent, tint = BOARD_STYLES[number % len(BOARD_STYLES)]
            used = list({c.terminal for c in shown if (c.daq, c.terminal.dev) == (daq, dev)})
            local_owners = {t: owners.get((daq, t)) for t in used}
            height = HEADER + ROW * len(used)
            body = self._box(x, y, TERMINAL_WIDTH, height)
            body.setPen(QtGui.QPen(QtGui.QColor(accent), 2.5))
            body.setBrush(QtGui.QBrush(QtGui.QColor(tint)))
            header = self._box(x, y, TERMINAL_WIDTH, HEADER)
            header.setPen(QtGui.QPen(QtGui.QColor(accent), 2.5))
            header.setBrush(QtGui.QBrush(QtGui.QColor(accent)))
            self._text(self._board_title(analysis, daq, dev), x + TERMINAL_WIDTH / 2,
                       y + HEADER / 2, "#FFFFFF", bold=True, align="center")
            for row, terminal in enumerate(terminal_order(used, local_owners)):
                center = y + HEADER + ROW * (row + 0.5)
                terminal_y[daq, terminal] = center
                self._text(terminal.label, x + TERMINAL_WIDTH / 2, center,
                           self._terminal_color(users[daq, terminal]), align="center")
            y += height + BOARD_SPACING
        return terminal_y

    @staticmethod
    def _board_title(analysis: RigAnalysis, daq: str, dev: str) -> str:
        board = board_for(analysis.boards, daq, dev)
        parts = [daq, dev] if dev else [daq]
        if board is not None:
            parts.append(f"({board.model})")
        return "  ".join(parts)

    @staticmethod
    def _terminal_color(connections: list) -> str:
        kinds = [c.kind for c in connections if c.active] or [c.kind for c in connections]
        return KIND_COLORS.get(kinds[0], UNKNOWN_KIND)

    @staticmethod
    def _source_label(connection: Connection, boards: set) -> str:
        """The DAQ terminal of a port, naming the board only if there are several."""
        terminal = connection.terminal
        if len(boards) < 2 or not terminal.dev:
            return terminal.label
        if len({daq for daq, _dev in boards}) > 1:
            return f"{connection.daq} {terminal.dev}/{terminal.label}"
        return f"{terminal.dev}/{terminal.label}"

    @staticmethod
    def _text_width(text: str) -> float:
        font = QtWidgets.QGraphicsSimpleTextItem().font()
        font.setPointSize(10)
        return QtGui.QFontMetricsF(font).horizontalAdvance(text)

    def _draw_side(self, by_device: dict, terminal_y: dict, styles: dict, problems: set,
                   boards: set, users: dict, x: float, daq_edge: float, side: str) -> None:
        def position(name: str) -> tuple:
            lowest = min(terminal_y[c.daq, c.terminal] for c in by_device[name])
            # Left-side wires stay uncrossed only if the devices follow the terminals.
            return (lowest,) if side == "left" else (not by_device[name][0].active, lowest)

        device_edge = x + DEVICE_WIDTH if side == "left" else x
        align = "right" if side == "left" else "left"
        text_x = x + DEVICE_WIDTH - 8 if side == "left" else x + 8
        # The DAQ terminal of each port is in a column beside the incoming wires.
        column = SOURCE_GAP + max(self._text_width(self._source_label(c, boards))
                                  for connections in by_device.values() for c in connections)
        port_x = text_x - column if side == "left" else text_x + column
        y = 0.0
        for name in sorted(by_device, key=position):
            connections = sorted(by_device[name], key=lambda c: terminal_y[c.daq, c.terminal])
            muted = not connections[0].active
            height = HEADER + ROW * len(connections)
            self._box(x, y, DEVICE_WIDTH, height, muted)
            title = f"{name}  (commented out)" if muted else name
            self._text(title, text_x, y + HEADER / 2, MUTED if muted else TEXT, bold=True,
                       align=align)
            for row, connection in enumerate(connections):
                center = y + HEADER + ROW * (row + 0.5)
                problem = connection.active and (connection.daq, connection.terminal) in problems
                color = PROBLEM if problem else KIND_COLORS.get(connection.kind, UNKNOWN_KIND)
                self._text(self._source_label(connection, boards), text_x, center,
                           self._terminal_color(users[connection.daq, connection.terminal]),
                           align=align)
                self._text(connection.port, port_x, center, color, bold=problem, align=align)
                self._wire(
                    QtCore.QPointF(daq_edge, terminal_y[connection.daq, connection.terminal]),
                    QtCore.QPointF(device_edge, center),
                    connection,
                    styles[id(connection)],
                )
            y += height + DEVICE_SPACING

