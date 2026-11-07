"""Формы работают через Application, без SQLite и Infrastructure."""
import ast
from pathlib import Path


def test_presentation_has_no_sqlite_access():
    root = Path(__file__).resolve().parents[2] / "src/healthtracker/presentation"
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            modules = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            assert not any(name == "sqlite3" or name.startswith("healthtracker.infrastructure")
                           for name in modules), path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"execute", "executemany", "executescript"}, path
