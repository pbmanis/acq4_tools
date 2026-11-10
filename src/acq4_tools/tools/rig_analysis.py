"""Work out what a devices.cfg connects to what, and what is wrong with it. No GUI."""

import re
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Optional

from acq4_tools.common.acq4_source import NOT_FOUND, SourceCatalog
from acq4_tools.common.config_document import ConfigDocument, ConfigError, Node, parse_text
from acq4_tools.common.config_document import read_config_text
from acq4_tools.common.paths import packaged_data

BOARD_PREFIX = "## acq4_tools board"
ALTERNATES_PREFIX = "## acq4_tools alternates:"

ANALOG_TYPES = ("ai", "ao")
DIGITAL_TYPES = ("di", "do")
AI_MODES = ("rse", "nrse", "diff")
REFERENCE_KEYS = (
    "clampDevice", "pipetteDevice", "pressureDevice", "defaultCamera", "defaultLaser",
    "defaultPowerMeter", "focusDevice", "imagingDevice", "daqDev", "recordingChambers",
    "shutterLasers",
)
_KIND_ORDER = {"ai": 0, "ao": 1, "p0": 2, "pfi": 3, "other": 4}
_HEADER = re.compile(r"^( *)([^\s#:][^:#]*):\s*(#.*)?$")
_BOARD_LINE = re.compile(r"^(.+?):\s*(\S+)\s+ai=(\d+)\s+ao=(\d+)\s+port0=(\d+)\s+pfi=(\d+)\s*$")


@dataclass(frozen=True)
class Board:
    model: str
    ai: int
    ao: int
    port0: int
    pfi: int


def _standard_boards() -> dict:
    # M and X series: PFI 0-15 are the lines of ports 1 and 2.
    small = ("6221", "6251", "6281", "6321", "6341", "6351", "6361")
    large = ("6229", "6259", "6289", "6323", "6343", "6353", "6363")
    boards = {model: Board(model, 16, 2, 8, 16) for model in small}
    boards.update({model: Board(model, 32, 4, 32, 16) for model in large})
    return dict(sorted(boards.items()))


BOARD_MODELS = _standard_boards()
CUSTOM_MODEL = "Custom"


@dataclass(frozen=True)
class Terminal:
    dev: str
    kind: str  # ai, ao, p0, pfi or other
    index: int = 0
    name: str = ""

    @property
    def label(self) -> str:
        if self.kind == "p0":
            return f"P0.{self.index}"
        if self.kind == "pfi":
            return f"PFI{self.index}"
        return self.name if self.kind == "other" else f"{self.kind}{self.index}"

    @property
    def sort_key(self) -> tuple:
        return self.dev, _KIND_ORDER[self.kind], self.index, self.name


def parse_terminal(channel: str, board: Optional[Board] = None) -> Terminal:
    """The physical terminal of a channel name. '/Dev1/line30', '/Dev1/port0/line30'
    and, for lines beyond port 0, '/Dev1/PFI5' can all name the same screw terminal."""
    match = re.match(r"^/?([^/]+)/(.+)$", channel)
    if match is None:
        return Terminal("", "other", name=channel)
    dev, rest = match[1], match[2].lower()
    if found := re.fullmatch(r"(ai|ao)(\d+)", rest):
        return Terminal(dev, found[1], int(found[2]))
    if found := re.fullmatch(r"pfi(\d+)", rest):
        return Terminal(dev, "pfi", int(found[1]))
    if found := re.fullmatch(r"line(\d+)", rest):
        line = int(found[1])
        if board is not None and line >= board.port0:
            return Terminal(dev, "pfi", line - board.port0)
        return Terminal(dev, "p0", line)
    if found := re.fullmatch(r"port(\d+)/line(\d+)", rest):
        port, line = int(found[1]), int(found[2])
        if port == 0:
            return Terminal(dev, "p0", line)
        if port in (1, 2):
            return Terminal(dev, "pfi", line + (port - 1) * 8)
    return Terminal(dev, "other", name=match[2])


def terminal_exists(terminal: Terminal, board: Board) -> bool:
    limits = {"ai": board.ai, "ao": board.ao, "p0": board.port0, "pfi": board.pfi}
    return terminal.index < limits[terminal.kind] if terminal.kind in limits else False


def board_for(boards: dict, daq: str, dev: str) -> Optional[Board]:
    """A DAQ driving several boards can have one entry each, as 'DAQ/Dev2'."""
    return boards.get(f"{daq}/{dev}") or boards.get(daq)


def differential_partner(index: int) -> Optional[int]:
    """The negative input of a differential channel; None if it cannot be positive."""
    return index + 8 if index % 16 < 8 else None


@dataclass
class RigDevice:
    name: str
    driver: Optional[str]
    config: dict
    active: bool
    order: int = -1  # position among the active devices
    start: int = -1  # where a commented-out block is, in lines of the file
    end: int = -1
    base: int = 0  # columns of indent to remove on bringing it back


@dataclass
class Connection:
    daq: str
    channel: str
    terminal: Terminal
    kind: Optional[str]  # ai, ao, di, do, trigger, or None if not stated
    device: str
    port: str
    active: bool
    mode: Optional[str] = None
    legacy: bool = False
    settings: dict = field(default_factory=dict)
    pair: Optional[Terminal] = None  # negative input of a differential channel
    place: str = ""  # the terminal as shown to the user, with its board if there are several

    @property
    def user(self) -> str:
        return f"{self.device} ({self.port})"

    @property
    def occupied(self) -> list:
        return [self.terminal] if self.pair is None else [self.terminal, self.pair]


@dataclass
class SharedLine:
    daq: str
    terminal: Terminal
    users: list  # Connections
    marked: bool
    place: str = ""

    @property
    def devices(self) -> list:
        return sorted({c.device for c in self.users})


@dataclass
class LineRow:
    daq: str
    terminal: Terminal
    active: list
    alternates: list
    status: str
    shared: Optional[SharedLine] = None
    place: str = ""


@dataclass
class OptoNode:
    device: RigDevice
    transform: str
    children: list = field(default_factory=list)


@dataclass
class KeyRow:
    device: str
    driver: str
    key: str
    status: str
    active: bool


@dataclass
class RigAnalysis:
    devices: list
    daqs: list
    connections: list
    shared: list
    line_rows: list
    opto_roots: list
    key_rows: list
    findings: list
    boards: dict
    alternates: list
    unreadable_blocks: int = 0
    board_keys: list = field(default_factory=list)  # one per board that can be chosen


# ----------------------------------------------------------------------
# reading the file
# ----------------------------------------------------------------------
def _uncomment(line: str) -> str:
    return line[2:] if line[1:2] == " " else line[1:]


def _indent(text: str) -> int:
    return len(text) - len(text.lstrip(" "))


def find_commented_devices(text: str) -> tuple:
    """Devices that have been commented out. Returns them, and the number of
    blocks that mention a driver but could not be read."""
    lines = text.replace("\\\n", "").split("\n")
    devices = []
    unreadable = 0
    index = 0
    while index < len(lines):
        header = _HEADER.match(_uncomment(lines[index])) if lines[index].startswith("#") else None
        if header is None:
            index += 1
            continue
        base = len(header[1])
        end = index + 1
        while end < len(lines) and lines[end].startswith("#"):
            body = _uncomment(lines[end])
            if body.strip() and not body.lstrip().startswith("#") and _indent(body) <= base:
                break
            end += 1
        block = [_uncomment(line)[base:] for line in lines[index:end]]
        try:
            data = parse_text("\n".join(block))
        except ConfigError:
            data = None
            unreadable += any(re.match(r"\s*driver\s*:", line) for line in block)
        config = next(iter(data.values())) if data else None
        if isinstance(config, dict) and isinstance(config.get("driver"), str):
            devices.append(RigDevice(header[2].strip(), config["driver"], config, False,
                                     start=index, end=end, base=base))
            index = end
        else:
            index = end if data is None and end > index + 1 else index + 1
    return devices, unreadable


def read_boards(doc: ConfigDocument) -> dict:
    boards = {}
    for value in doc.annotations(BOARD_PREFIX):
        if match := _BOARD_LINE.match(value):
            boards[match[1].strip()] = Board(match[2], *(int(match[i]) for i in range(3, 7)))
    return boards


def write_boards(doc: ConfigDocument, boards: dict) -> bool:
    return doc.set_annotations(BOARD_PREFIX, [
        f"{daq}: {b.model} ai={b.ai} ao={b.ao} port0={b.port0} pfi={b.pfi}"
        for daq, b in sorted(boards.items())
    ])


def read_alternates(doc: ConfigDocument) -> list:
    groups = [{name.strip() for name in value.split("|") if name.strip()}
              for value in doc.annotations(ALTERNATES_PREFIX)]
    return [group for group in groups if len(group) > 1]


def write_alternates(doc: ConfigDocument, groups: list) -> bool:
    return doc.set_annotations(ALTERNATES_PREFIX, [" | ".join(sorted(g)) for g in groups])


def _are_alternates(first: str, second: str, groups: list) -> bool:
    return any(first in group and second in group for group in groups)


# ----------------------------------------------------------------------
# connections
# ----------------------------------------------------------------------
def _settings_of(device: RigDevice) -> dict:
    # The Manager uses a nested "config" section in place of the device's keys.
    nested = device.config.get("config")
    return nested if isinstance(nested, dict) else device.config


def _descends(catalog: Optional[SourceCatalog], driver: Optional[str], ancestor: str) -> bool:
    if driver == ancestor:
        return True
    return catalog is not None and driver is not None and catalog.descends(driver, ancestor)


def _make_connection(device: RigDevice, daq: str, channel: str, kind: Optional[str], port: str,
                     boards: dict, default_modes: dict, settings: dict,
                     legacy: bool = False) -> Connection:
    match = re.match(r"^/?([^/]+)/", channel)
    terminal = parse_terminal(channel, board_for(boards, daq, match[1] if match else ""))
    mode = settings.get("mode")
    connection = Connection(daq, channel, terminal, kind, device.name, port, device.active,
                            mode, legacy, settings)
    if kind == "ai" and terminal.kind == "ai":
        effective = mode if mode is not None else default_modes.get(daq)
        if isinstance(effective, str) and effective.lower() == "diff":
            partner = differential_partner(terminal.index)
            if partner is not None:
                connection.pair = Terminal(terminal.dev, "ai", partner)
    return connection


def _collect_connections(device: RigDevice, daqs: set, boards: dict, default_modes: dict,
                         catalog: Optional[SourceCatalog]) -> list:
    found = []
    settings = _settings_of(device)
    if _descends(catalog, device.driver, "Trigger"):
        for daq, channel in (settings.get("channels") or {}).items():
            if daq in daqs and isinstance(channel, str):
                found.append(_make_connection(device, daq, channel, "trigger", "trigger",
                                              boards, default_modes, {}))
    inferred = "di" if _descends(catalog, device.driver, "DIOSwitch") else None

    def walk(mapping: dict, path: list) -> None:
        for key, value in mapping.items():
            port = ".".join([*path, str(key)]).removeprefix("channels.")
            if _is_old_channel(value, daqs):
                kind = "trigger" if "triggerOut" in str(key) else None
                found.append(_make_connection(device, value[0], value[1], kind, port, boards,
                                              default_modes, {}, legacy=True))
            elif isinstance(value, dict):
                if value.get("virtual"):
                    continue
                if isinstance(value.get("channel"), str) and isinstance(value.get("device"), str):
                    fallback = "trigger" if "triggerOut" in str(key) else inferred
                    kind = value.get("type") or fallback
                    found.append(_make_connection(device, value["device"], value["channel"], kind,
                                                  port, boards, default_modes, value))
                elif _is_old_channel(value.get("channel"), daqs):
                    pair = value["channel"]
                    found.append(_make_connection(device, pair[0], pair[1], value.get("type"),
                                                  port, boards, default_modes, value, legacy=True))
                else:
                    walk(value, [*path, str(key)])

    if not _descends(catalog, device.driver, "Trigger"):
        walk(settings, [])
    return found


def channel_name(terminal: Terminal) -> str:
    """The name to write in the file for a terminal."""
    if terminal.kind == "p0":
        return f"/{terminal.dev}/port0/line{terminal.index}"
    if terminal.kind == "pfi":
        return f"/{terminal.dev}/PFI{terminal.index}"
    return f"/{terminal.dev}/{terminal.label}"


@dataclass(frozen=True)
class DeviceExample:
    name: str
    driver: str
    text: str

    def text_named(self, name: str) -> str:
        return name + self.text[self.text.index(":"):]


def device_examples() -> list:
    """The devices in acq4's example devices.cfg, active and commented out."""
    text = read_config_text(packaged_data("devices_template.cfg"))
    doc = ConfigDocument(text)
    examples = [DeviceExample(n.key, doc.value(n.child("driver")), doc.block_text(n))
                for n in doc.root.children if n.child("driver") is not None]
    lines = [line.logical for line in doc.lines]
    for device in find_commented_devices(text)[0]:
        body = [_uncomment(line)[device.base:] for line in lines[device.start:device.end]]
        examples.append(DeviceExample(device.name, device.driver, "\n".join(body)))
    return examples


def rename_device(doc: ConfigDocument, node: Node, new_name: str) -> None:
    """Rename a device, along with everything in the file that refers to it."""
    old_name = node.key
    doc.rename(node, new_name)

    def replaced(value: Any) -> Any:
        if value == old_name:
            return new_name
        if isinstance(value, (list, tuple)):
            return type(value)(new_name if item == old_name else item for item in value)
        return value

    def visit(parent: Node) -> None:
        for child in parent.children:
            if child.is_section:
                visit(child)
            elif child.key in ("parentDevice", "device", "objectiveSwitch", *REFERENCE_KEYS) \
                    or (child.key == "name" and parent.key == "parentDevice"):
                value = doc.value(child)
                if replaced(value) != value:
                    doc.set_value(child, replaced(value))
            elif child.key == old_name and parent.key == "channels" and not child.is_section:
                doc.rename(child, new_name)

    visit(doc.root)
    boards = {}
    for key, board in read_boards(doc).items():
        daq, slash, dev = key.partition("/")
        boards[f"{new_name if daq == old_name else daq}{slash}{dev}"] = board
    write_boards(doc, boards)
    write_alternates(doc, [{new_name if n == old_name else n for n in group}
                           for group in read_alternates(doc)])


def _is_old_channel(value: Any, daqs: set) -> bool:
    return isinstance(value, tuple) and len(value) >= 2 and isinstance(value[0], str) \
        and value[0] in daqs and isinstance(value[1], str) and "/" in value[1]


# ----------------------------------------------------------------------
# checks
# ----------------------------------------------------------------------
def _check_connection(connection: Connection, device: RigDevice, active_names: set, daqs: set,
                      boards: dict, catalog: Optional[SourceCatalog], findings: list) -> None:
    label = f"{connection.device}, {connection.port}"
    if connection.daq not in daqs:
        if connection.daq in active_names:
            findings.append(f"Error: {label}: '{connection.daq}' is not a DAQ device.")
        else:
            findings.append(f"Error: {label}: there is no active DAQ named '{connection.daq}'.")
        return
    if connection.legacy:
        findings.append(f"Warning: {label}: the ('DAQ', 'line') form is out of date; "
                        "acq4 now expects separate device and channel keys.")
    terminal, kind = connection.terminal, connection.kind
    if terminal.kind == "other":
        findings.append(f"Warning: {label}: cannot interpret channel '{connection.channel}'.")
    is_generic = _descends(catalog, device.driver, "DAQGeneric")
    if kind is None and is_generic:
        findings.append(f"Error: {label}: no type is given (ai, ao, di or do).")
    elif kind is not None and kind not in (*ANALOG_TYPES, *DIGITAL_TYPES, "trigger"):
        findings.append(f"Error: {label}: type '{kind}' is not ai, ao, di or do.")
    elif terminal.kind != "other" and not _type_fits_terminal(kind, terminal):
        findings.append(f"Error: {label}: type '{kind}' does not fit terminal {connection.place}.")
    if is_generic and kind in DIGITAL_TYPES and (
        "scale" in connection.settings or "offset" in connection.settings
    ):
        findings.append(f"Error: {label}: scale and offset are only allowed on analog channels.")
    if is_generic and kind in ANALOG_TYPES and connection.settings.get("invert"):
        findings.append(f"Error: {label}: invert is only allowed on digital channels.")
    if isinstance(connection.mode, str) and connection.mode.lower() not in AI_MODES:
        findings.append(f"Error: {label}: mode '{connection.mode}' is not rse, nrse or diff.")
    board = board_for(boards, connection.daq, terminal.dev)
    if board is not None and terminal.kind != "other" and not terminal_exists(terminal, board):
        findings.append(f"Error: {label}: {connection.place} does not exist on {board.model}.")
    mode = connection.mode
    if connection.pair is None and terminal.kind == "ai" and kind == "ai" \
            and isinstance(mode, str) and mode.lower() == "diff":
        findings.append(f"Error: {label}: {connection.place} is the negative side of a "
                        "differential pair and cannot be a differential channel.")


def _type_fits_terminal(kind: Optional[str], terminal: Terminal) -> bool:
    if kind in ("ai", "ao"):
        return terminal.kind == kind
    if kind in DIGITAL_TYPES:
        return terminal.kind in ("p0", "pfi")
    return True


def _boards_in_use(connections: list) -> dict:
    """The board names (Dev1, Dev2, ...) that each DAQ device uses."""
    boards: dict = defaultdict(set)
    for connection in connections:
        if connection.terminal.dev:
            boards[connection.daq].add(connection.terminal.dev)
    return {daq: sorted(names) for daq, names in boards.items()}


def _place(terminal: Terminal, devs: list) -> str:
    return f"{terminal.dev}/{terminal.label}" if len(devs) > 1 and terminal.dev else terminal.label


def _find_shared(connections: list, groups: list, daq_devs: dict) -> list:
    users = defaultdict(list)
    for connection in connections:
        if connection.active:
            for terminal in connection.occupied:
                users[connection.daq, terminal].append(connection)
    shared = []
    for (daq, terminal), connected in sorted(users.items(),
                                             key=lambda i: (i[0][0], i[0][1].sort_key)):
        if len(connected) > 1:
            names = sorted({c.device for c in connected})
            marked = len(names) == len(connected) and all(
                _are_alternates(a, b, groups) for a, b in combinations(names, 2)
            )
            shared.append(SharedLine(daq, terminal, connected, marked,
                                     _place(terminal, daq_devs.get(daq, []))))
    return shared


def _all_terminals(board: Board, dev: str) -> list:
    return [
        *(Terminal(dev, "ai", i) for i in range(board.ai)),
        *(Terminal(dev, "ao", i) for i in range(board.ao)),
        *(Terminal(dev, "p0", i) for i in range(board.port0)),
        *(Terminal(dev, "pfi", i) for i in range(board.pfi)),
    ]


def _line_rows(daqs: list, connections: list, shared: list, boards: dict,
               daq_devs: dict) -> list:
    rows = []
    shared_lookup = {(s.daq, s.terminal): s for s in shared}
    for daq in daqs:
        mine = [c for c in connections if c.daq == daq]
        active: dict = defaultdict(list)
        alternates: dict = defaultdict(list)
        for connection in mine:
            target = active if connection.active else alternates
            target[connection.terminal].append(connection.user)
            if connection.pair is not None:
                target[connection.pair].append(f"{connection.user} negative input")
        terminals = set(active) | set(alternates)
        for dev in daq_devs.get(daq) or ["Dev1"]:
            board = board_for(boards, daq, dev)
            if board is not None:
                terminals.update(_all_terminals(board, dev))
        for terminal in sorted(terminals, key=lambda t: t.sort_key):
            entry = shared_lookup.get((daq, terminal))
            board = board_for(boards, daq, terminal.dev)
            if board is not None and not terminal_exists(terminal, board):
                status = "not on board"
            elif entry is not None:
                status = "alternates" if entry.marked else "shared"
            else:
                status = "in use" if active.get(terminal) else "free"
            rows.append(LineRow(daq, terminal, active.get(terminal, []),
                                alternates.get(terminal, []), status, entry,
                                _place(terminal, daq_devs.get(daq, []))))
    return rows


def _parent_name(settings: dict) -> Optional[str]:
    parent = settings.get("parentDevice")
    if isinstance(parent, dict):
        parent = parent.get("name")
    return parent if isinstance(parent, str) else None


def _number(value: Any) -> str:
    return f"{value:.4g}" if isinstance(value, float) else str(value)


def _format_vector(value: Any) -> str:
    if isinstance(value, (tuple, list)):
        return "(" + ", ".join(_number(v) for v in value) + ")"
    return _number(value)


def _transform_text(settings: dict) -> str:
    transform = settings.get("transform")
    if not isinstance(transform, dict):
        return ""
    return "; ".join(f"{key} {_format_vector(value)}" for key, value in transform.items())


def _check_transform(device: RigDevice, settings: dict, catalog: Optional[SourceCatalog],
                     findings: list) -> None:
    if "transform" not in settings:
        return
    transform = settings["transform"]
    if not isinstance(transform, dict):
        findings.append(f"Error: {device.name}: transform must have nested settings.")
        return
    allowed = catalog.transform_keys if catalog else frozenset(("pos", "scale", "angle", "axis"))
    for key in transform:
        if key not in allowed:
            findings.append(f"Error: {device.name}: transform key '{key}' is not allowed; "
                            f"acq4 accepts {', '.join(sorted(allowed))}.")
    scale = transform.get("scale")
    if isinstance(scale, (tuple, list)) and any(v == 0 for v in scale):
        findings.append(f"Warning: {device.name}: a transform scale of 0 cannot be inverted.")


def _build_tree(active: list, catalog: Optional[SourceCatalog], findings: list) -> list:
    by_name = {device.name: device for device in active}
    participants = set()
    for device in active:
        settings = _settings_of(device)
        if _descends(catalog, device.driver, "OptomechDevice") or "parentDevice" in settings \
                or "transform" in settings:
            participants.add(device.name)
            parent = _parent_name(settings)
            if parent in by_name:
                participants.add(parent)
    nodes = {name: OptoNode(by_name[name], _transform_text(_settings_of(by_name[name])))
             for name in by_name if name in participants}
    roots = []
    for name, node in nodes.items():
        device = node.device
        settings = _settings_of(device)
        _check_transform(device, settings, catalog, findings)
        parent = _parent_name(settings)
        if "parentDevice" in settings and parent is None:
            findings.append(f"Error: {name}: parentDevice is not a device name.")
        if parent is None:
            roots.append(node)
        elif parent not in nodes:
            findings.append(f"Error: {name}: parent '{parent}' is not an active device; "
                            "acq4 will leave it unconnected.")
            roots.append(node)
        else:
            nodes[parent].children.append(node)
            parent_device = by_name[parent]
            if parent_device.order >= device.order:
                findings.append(f"Error: {name} is defined before its parent {parent}. "
                                "acq4 loads devices in file order and will leave it unconnected.")
            if catalog is not None and catalog.is_driver(parent_device.driver or "") \
                    and not catalog.descends(parent_device.driver, "OptomechDevice"):
                findings.append(f"Warning: {name}: parent {parent} "
                                f"({parent_device.driver}) is not an optomechanical device.")
    reached = set()

    def visit(node: OptoNode) -> None:
        reached.add(node.device.name)
        for child in node.children:
            visit(child)

    for root in roots:
        visit(root)
    for name, node in nodes.items():
        if name not in reached:
            findings.append(f"Error: {name} is part of a loop of parent devices.")
            node.children = []
            roots.append(node)
            reached.add(name)
    return roots


def _check_references(device: RigDevice, active_names: set, findings: list) -> None:
    settings = _settings_of(device)
    names = []
    for key in REFERENCE_KEYS:
        value = settings.get(key)
        if isinstance(value, str):
            names.append((key, value))
        elif isinstance(value, (list, tuple)):
            names.extend((key, item) for item in value if isinstance(item, str))
    switch = settings.get("objectiveSwitch")
    if isinstance(switch, (list, tuple)) and switch and isinstance(switch[0], str):
        names.append(("objectiveSwitch", switch[0]))
    for key, name in names:
        if name not in active_names:
            findings.append(f"Warning: {device.name}: {key} '{name}' is not an active device.")


def _key_rows(devices: list, catalog: SourceCatalog) -> list:
    rows = []
    for device in devices:
        if not device.driver or not catalog.is_driver(device.driver):
            continue
        is_generic = catalog.descends(device.driver, "DAQGeneric")
        for key, value in _settings_of(device).items():
            if key == "driver":
                continue
            if is_generic and isinstance(value, dict) and "channel" in value:
                status = "DAQ channel"
            else:
                status = catalog.key_status(device.driver, key)
            rows.append(KeyRow(device.name, device.driver, key, status, device.active))
    return rows


def _check_drivers(active: list, catalog: Optional[SourceCatalog], findings: list) -> None:
    for device in active:
        if not device.driver:
            findings.append(f"Error: {device.name} has no driver.")
        elif catalog is not None and "." not in device.driver \
                and not catalog.is_driver(device.driver):
            findings.append(f"Error: {device.name}: acq4 has no driver named '{device.driver}'.")


def _severity(finding: str) -> int:
    return {"Error": 0, "Warning": 1}.get(finding.partition(":")[0], 2)


def analyze(doc: ConfigDocument, catalog: Optional[SourceCatalog] = None) -> RigAnalysis:
    """Everything the tool shows about the file ``doc``."""
    active = []
    findings: list = []
    for node in doc.root.children:
        config = doc.value(node) if node.is_section else None
        if not isinstance(config, dict):
            findings.append(f"Error: {node.key} is not a device (it has no nested settings).")
            continue
        driver = config.get("driver")
        active.append(RigDevice(node.key, driver if isinstance(driver, str) else None, config,
                                True, len(active)))
    commented, unreadable = find_commented_devices(doc.text())
    devices = [*active, *commented]
    active_names = {device.name for device in active}

    daqs = [d.name for d in active if _descends(catalog, d.driver, "NiDAQ")]
    known_daqs = set(daqs) | {d.name for d in commented if _descends(catalog, d.driver, "NiDAQ")}
    boards = read_boards(doc)
    groups = read_alternates(doc)
    default_modes = {d.name: _settings_of(d).get("defaultAIMode") for d in devices
                     if d.name in known_daqs}

    _check_drivers(active, catalog, findings)
    by_device = {}
    for device in devices:
        by_device[id(device)] = _collect_connections(device, known_daqs, boards, default_modes,
                                                     catalog)
    connections = [c for made in by_device.values() for c in made]
    daq_devs = _boards_in_use(connections)
    for connection in connections:
        connection.place = _place(connection.terminal, daq_devs.get(connection.daq, []))
    for device in devices:
        if device.active:
            for connection in by_device[id(device)]:
                _check_connection(connection, device, active_names, set(daqs), boards, catalog,
                                  findings)
                daq = next((d for d in active if d.name == connection.daq), None)
                if daq is not None and daq.order > device.order:
                    findings.append(f"Warning: {device.name} is defined before its DAQ "
                                    f"{connection.daq}; acq4 loads devices in file order.")
            _check_references(device, active_names, findings)

    known_ports = {(c.device, c.port.split(".")[0]) for c in connections}
    key_rows = [] if catalog is None else _key_rows(devices, catalog)
    for row in key_rows:
        if row.active and row.status == NOT_FOUND and (row.device, row.key) not in known_ports:
            findings.append(f"Warning: {row.device}: the {row.driver} driver does not "
                            f"use the key '{row.key}'.")

    shared = _find_shared(connections, groups, daq_devs)
    for entry in shared:
        if not entry.marked:
            users = ", ".join(c.user for c in entry.users)
            findings.append(f"Warning: {entry.daq} {entry.place} is shared by {users}.")
    board_keys = []
    for daq in daqs:
        devs = daq_devs.get(daq, [])
        several = len(devs) > 1
        for dev in devs if several else devs[:1] or [""]:
            key = f"{daq}/{dev}" if several else daq
            board_keys.append(key)
            if board_for(boards, daq, dev) is None:
                findings.append(f"Note: choose a board for {key} to check that its lines exist.")
    if catalog is None:
        findings.append("Note: choose the acq4 directory to check names against its source.")
    if unreadable:
        findings.append(f"Note: {unreadable} commented-out device block(s) could not be read.")

    roots = _build_tree(active, catalog, findings)
    findings = list(dict.fromkeys(findings))
    findings.sort(key=_severity)
    return RigAnalysis(devices, daqs, connections, shared,
                       _line_rows(daqs, connections, shared, boards, daq_devs), roots, key_rows,
                       findings, boards, groups, unreadable, board_keys)
