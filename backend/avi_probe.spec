# T01-A fixture. A separate product spec will use app/entrypoint.py in T01-B.
from pathlib import Path

root = Path(SPECPATH)
analysis = Analysis(
    [str(root / "probes" / "entrypoint.py")],
    pathex=[str(root)], binaries=[], datas=[], hiddenimports=[],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [], exclude_binaries=True, name="avi_probe",
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
    console=True, disable_windowed_traceback=False,
)
collection = COLLECT(
    exe, analysis.binaries, analysis.datas, strip=False, upx=False, name="avi_probe",
)
