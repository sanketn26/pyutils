def test_engine_module_parses() -> None:
    import ast
    from pathlib import Path

    engine = Path(__file__).resolve().parents[1] / "src" / "workflow_engine" / "engine.py"
    ast.parse(engine.read_text(encoding="utf-8"))
