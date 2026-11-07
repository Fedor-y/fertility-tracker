# Linux x86_64 onedir. Пользовательская база в сборку не входит.
from pathlib import Path

root = Path(SPECPATH).parent
a = Analysis(
    [str(root / "packaging" / "launcher.py")],
    pathex=[str(root / "src"), str(root / "packaging")],
    datas=[(str(root / "src/healthtracker/resources/chart"), "healthtracker/resources/chart")],
    hiddenimports=[],
    excludes=["pytest", "pytestqt"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="healthtracker", console=True)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="healthtracker")
