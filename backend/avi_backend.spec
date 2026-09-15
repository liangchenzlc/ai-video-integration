from pathlib import Path

root = Path(SPECPATH)
analysis = Analysis(
    [str(root / "app" / "entrypoint.py")], pathex=[str(root)],
    binaries=[], datas=[], hiddenimports=["uvicorn.logging", "uvicorn.loops.asyncio", "uvicorn.protocols.http.h11_impl", "uvicorn.lifespan.on"],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[], noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, name="avi_backend",
          debug=False, strip=False, upx=False, console=True)
collection = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False, name="avi_backend")
