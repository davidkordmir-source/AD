"""Bundle the independent Qt/GDAL app as one .py with no project-side imports."""

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class FlattenFast(ast.NodeTransformer):
    def visit_ImportFrom(self, node):
        if node.level or (node.module or "").startswith("sector_viewshed"):
            return None
        return node

    def visit_If(self, node):
        if ast.unparse(node.test) == "__name__ == '__main__'":
            return None
        return self.generic_visit(node)


def build_fast():
    diagnostic_tree = ast.parse((ROOT/"fast_viewshed/diagnostics.py").read_text(encoding="utf-8"))
    nodes = FlattenFast().visit(diagnostic_tree).body
    application = []
    core = ast.parse((ROOT/"sector_viewshed/core.py").read_text(encoding="utf-8"))
    for node in core.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            application.append(node)
        elif isinstance(node, ast.Assign):
            application.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in {"number", "_degrees", "azimuth", "angle_ranges"}:
            application.append(node)
    for name in ("model", "engine", "basemap", "gui"):
        tree = ast.parse((ROOT/"fast_viewshed"/(name+".py")).read_text(encoding="utf-8"))
        application.extend(FlattenFast().visit(tree).body)
    application.extend(ast.parse('''
if __name__ == "__main__":
    raise SystemExit(fast_main())
''').body)
    guard = ast.parse('''
try:
    if __name__ == "__main__":
        enable_fast_logging()
    pass
except Exception as _fast_startup_exception:
    if __name__ == "__main__":
        fast_startup_error(_fast_startup_exception)
        raise SystemExit(1)
    raise
''').body[0]
    guard.body = guard.body[:-1]+application
    nodes.append(guard)
    source = '# -*- coding: utf-8 -*-\n# Independent Qt GUI; requires GDAL, NumPy and PySide6, never ArcPy.\n'
    source += ast.unparse(ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[])))+"\n"
    parsed = ast.parse(source, feature_version=(3, 10))
    assert not any(isinstance(n, ast.ImportFrom) and n.level for n in ast.walk(parsed))
    for name in ("FastViewshed_GUI.py", "FastViewshed_GUI_COPY.txt"):
        (ROOT/name).write_text(source, encoding="utf-8")
    print("Built independent single-file GUI:", len(source.splitlines()), "lines")


if __name__ == "__main__":
    build_fast()
