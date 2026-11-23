import ast
from pathlib import Path

CONTRACT = Path(__file__).resolve().parents[2] / "contracts" / "source_median.py"


def test_every_contract_method_takes_self_and_returns_a_type():
    tree = ast.parse(CONTRACT.read_text(encoding="utf8"))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SourceMedian")
    bad = []
    for node in cls.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = [a.arg for a in node.args.args]
        if not args or args[0] != "self":
            bad.append(f"{node.name}: missing self")
        if node.name != "__init__" and node.returns is None:
            bad.append(f"{node.name}: missing return annotation")
    assert not bad, "; ".join(bad)
