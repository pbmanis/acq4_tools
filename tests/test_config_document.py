import pytest

from acq4_tools.common.config_document import (
    ConfigDocument,
    ConfigError,
    IncludedFile,
    parse_text,
    read_config_text,
    split_comment,
    write_config_text,
)
from acq4_tools.common.paths import packaged_data

SAMPLE = """## heading

devices: readConfigFile('devices.cfg')  # the devices

modules:
    ## The data manager
    Data Manager:
        module:  'DataManager'
        shortcut: 'F2'
    # Old:
    #     module: 'Old'
    Patch:
        module: 'Patch'  ## patch
        config:
            clampDev: 'MC1'

misc:
    compression: None
    long: 1, \\
          2

    # storageDir: '/home/user/data'

last: "a # not a comment"
"""


def test_unedited_text_is_returned_exactly():
    assert ConfigDocument(SAMPLE).text() == SAMPLE


@pytest.mark.parametrize("name", ["default_template.cfg", "folderTypes_template.cfg"])
def test_packaged_templates_are_preserved_and_match_pyqtgraph(name):
    text = read_config_text(packaged_data(name))
    doc = ConfigDocument(text)
    assert doc.text() == text
    assert doc.value(doc.root) == parse_text(text)


def test_tree_matches_pyqtgraph():
    doc = ConfigDocument(SAMPLE)
    assert doc.value(doc.root) == parse_text(SAMPLE)
    assert doc.value(doc.node("devices")) == IncludedFile("devices.cfg")
    assert doc.value(doc.node("misc", "long")) == (1, 2)


def test_invalid_file_is_refused():
    with pytest.raises(ConfigError):
        ConfigDocument("a:\n        b: 1\n    c: 2\n")
    with pytest.raises(ConfigError):
        ConfigDocument("a: 1\na: 2\n")


@pytest.mark.parametrize(
    "text,value,rest",
    [
        ("1  # c", "1", "  # c"),
        ("'a#b' # c", "'a#b'", " # c"),
        ('"it\'s # x"', '"it\'s # x"', ""),
        ("   # only", "", "   # only"),
    ],
)
def test_split_comment(text, value, rest):
    assert split_comment(text) == (value, rest)


def only_changes(doc, old, new):
    return doc.text() == SAMPLE.replace(old, new, 1)


def test_set_value_keeps_spacing_and_comment():
    doc = ConfigDocument(SAMPLE)
    assert doc.set_value(doc.node("modules", "Patch", "module"), "Other")
    assert only_changes(doc, "module: 'Patch'  ## patch", "module: 'Other'  ## patch")


def test_setting_an_equal_value_changes_nothing():
    doc = ConfigDocument(SAMPLE)
    assert not doc.set_value(doc.node("modules", "Data Manager", "shortcut"), "F2")
    assert doc.text() == SAMPLE


def test_set_value_replaces_a_continued_line():
    doc = ConfigDocument(SAMPLE)
    doc.set_value(doc.node("misc", "long"), 5)
    assert only_changes(doc, "long: 1, \\\n          2", "long: 5")
    doc.check()


def test_add_goes_at_the_end_of_the_section():
    doc = ConfigDocument(SAMPLE)
    doc.add(doc.node("modules", "Patch", "config"), "rate", 100)
    assert only_changes(doc, "clampDev: 'MC1'\n", "clampDev: 'MC1'\n            rate: 100\n")
    doc.check()


def test_add_after_a_key():
    doc = ConfigDocument(SAMPLE)
    module = doc.node("modules", "Patch")
    doc.add(module, "shortcut", "F3", after=module.child("module"))
    assert [c.key for c in module.children] == ["module", "shortcut", "config"]
    doc.check()
    assert doc.value(doc.node("modules", "Patch", "shortcut")) == "F3"


def test_add_reuses_a_commented_out_line():
    doc = ConfigDocument(SAMPLE)
    doc.add(doc.node("misc"), "storageDir", "/data")
    assert only_changes(doc, "# storageDir: '/home/user/data'", "storageDir: '/data'")
    assert [c.key for c in doc.node("misc").children] == ["compression", "long", "storageDir"]


def test_commenting_out_and_back_in():
    doc = ConfigDocument(SAMPLE)
    misc = doc.node("misc")
    doc.comment_out(misc.child("compression"))
    assert only_changes(doc, "    compression: None", "    # compression: None")
    assert misc.child("compression") is None
    doc.add(misc, "compression", None)
    assert doc.text() == SAMPLE


def test_add_to_a_key_with_a_value_makes_a_section():
    doc = ConfigDocument("a:\n    config: None  # c\n")
    doc.add(doc.node("a", "config"), "x", 1)
    assert doc.text() == "a:\n    config:  # c\n        x: 1\n"
    doc.check()


def test_section_left_empty_stays_readable_at_the_end_of_a_file():
    doc = ConfigDocument("a:\n    b:\n        c: 1\n")
    doc.remove(doc.node("a", "b", "c"))
    assert doc.text() == "a:\n    b: {}\n"
    doc.check()
    doc.add(doc.node("a", "b"), "d", 2)
    assert doc.text() == "a:\n    b:\n        d: 2\n"
    doc.comment_out(doc.node("a", "b", "d"))
    doc.check()
    new = doc.add(doc.root, "e")
    assert new.line.text == "e: {}"
    doc.check()


def test_add_to_an_empty_section():
    doc = ConfigDocument("a:\nb: 1\n")
    doc.add(doc.node("a"), "x", 1)
    assert doc.text() == "a:\n    x: 1\nb: 1\n"


@pytest.mark.parametrize("key", ["", "a:b", " a", "#a", "Patch"])
def test_bad_names_are_refused(key):
    doc = ConfigDocument(SAMPLE)
    with pytest.raises(ConfigError):
        doc.add(doc.node("modules"), key, 1)
    assert doc.text() == SAMPLE


def test_remove_takes_description_but_not_a_commented_out_key():
    doc = ConfigDocument(SAMPLE)
    doc.remove(doc.node("modules", "Data Manager"))
    assert "The data manager" not in doc.text()
    assert "'DataManager'" not in doc.text()
    assert "# Old:" in doc.text()
    doc.check()

    doc = ConfigDocument(SAMPLE)
    doc.remove(doc.node("modules", "Patch"))
    assert "# Old:" in doc.text()
    assert "#     module: 'Old'" in doc.text()
    assert "clampDev" not in doc.text()
    doc.check()


def test_rename():
    doc = ConfigDocument(SAMPLE)
    doc.rename(doc.node("modules", "Data Manager"), "DM")
    assert only_changes(doc, "    Data Manager:", "    DM:")
    with pytest.raises(ConfigError):
        doc.rename(doc.node("modules", "DM"), "Patch")


def test_move_carries_the_whole_block():
    doc = ConfigDocument(SAMPLE)
    assert doc.move(doc.node("modules", "Patch"), -1)
    doc.check()
    assert list(doc.value(doc.node("modules"))) == ["Patch", "Data Manager"]
    text = doc.text()
    assert text.index("clampDev") < text.index("## The data manager") < text.index("'DataManager'")
    assert doc.value(doc.root) == {
        **parse_text(SAMPLE),
        "modules": {k: parse_text(SAMPLE)["modules"][k] for k in ("Patch", "Data Manager")},
    }


def test_move_at_the_ends_does_nothing():
    doc = ConfigDocument(SAMPLE)
    assert not doc.move(doc.node("modules", "Data Manager"), -1)
    assert not doc.move(doc.node("modules", "Patch"), 1)
    assert doc.text() == SAMPLE


def test_set_raw_checks_the_expression():
    doc = ConfigDocument(SAMPLE)
    node = doc.node("misc", "compression")
    assert doc.set_raw(node, "'gzip', 1")
    assert doc.value(node) == ("gzip", 1)
    with pytest.raises(ConfigError):
        doc.set_raw(node, "not valid (")


def test_write_keeps_a_backup_and_line_endings(tmp_path):
    path = tmp_path / "x.cfg"
    assert write_config_text(path, "a: 1\n") is None
    assert path.read_bytes() == b"a: 1\n"
    path.write_bytes(b"a: 1\r\nb: 2\r\n")
    backup = write_config_text(path, "a: 5\nb: 2\n")
    assert path.read_bytes() == b"a: 5\r\nb: 2\r\n"
    assert backup.read_bytes() == b"a: 1\r\nb: 2\r\n"
    assert read_config_text(path) == "a: 5\nb: 2\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.cfg", "x.cfg.bak"]
