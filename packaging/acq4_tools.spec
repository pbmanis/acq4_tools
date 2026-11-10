# PyInstaller build description for acq4 Tools. Run through the build_* scripts.
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH).parent
source = root / "src"

# pyqtgraph picks its Qt binding at run time and imports per-binding UI templates
# by name, which static analysis cannot see.
pyqtgraph_modules = [
    name
    for name in collect_submodules("pyqtgraph")
    if not any(part in name for part in ("_pyside", "_pyqt5", "opengl", "examples", "jupyter"))
]

analysis = Analysis(
    [str(source / "acq4_tools" / "__main__.py")],
    pathex=[str(source)],
    datas=[
        (str(source / "acq4_tools" / "data"), "acq4_tools/data"),
        *collect_data_files("pyqtgraph", includes=["colors/maps/*", "icons/**/*"]),
    ],
    # The toolbar imports each tool by name when its button is pressed.
    hiddenimports=[*collect_submodules("acq4_tools"), *pyqtgraph_modules],
    excludes=["PyQt5", "PySide2", "PySide6", "tkinter", "matplotlib", "IPython"],
)
pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="acq4-tools",
    console=False,
)
collection = COLLECT(exe, analysis.binaries, analysis.datas, name="acq4-tools")

if sys.platform == "darwin":
    app = BUNDLE(
        collection,
        name="acq4 Tools.app",
        bundle_identifier="org.acq4.tools",
        info_plist={"NSHighResolutionCapable": True},
    )
