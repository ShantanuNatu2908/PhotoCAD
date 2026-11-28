"""Fail on drift between Pydantic ADTs, the API spec, and the frontend types."""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

from pydantic import BaseModel

from app.schemas import adt

ROOT = Path(__file__).resolve().parents[2]
DOC_PATH = Path(os.getenv("PHOTOCAD_DOC_SCHEMA", ROOT / "docs" / "03_API_ADT_SPEC.md"))
TS_PATH = Path(os.getenv("PHOTOCAD_TS_SCHEMA", ROOT / "frontend" / "src" / "types" / "cad.ts"))

# These ADTs cross the REST/WebSocket boundary and therefore must exist in TypeScript.
SHARED_TS_MODELS = {
    "CalibrationSpec",
    "DetectedPlane",
    "DetectedCylinder",
    "Open3DGeometryReport",
    "ValidationMetrics",
}

errors: list[str] = []


def fail(message: str) -> None:
    errors.append(message)


def pydantic_models() -> dict[str, type[BaseModel]]:
    return {
        name: value
        for name, value in vars(adt).items()
        if isinstance(value, type) and issubclass(value, BaseModel) and value is not BaseModel
    }


def literal_values(annotation: Any) -> set[str]:
    """Collect Literal strings nested inside Optional/List/Union annotations."""
    if get_origin(annotation) is Literal:
        return {str(value) for value in get_args(annotation)}
    values: set[str] = set()
    for arg in get_args(annotation):
        values |= literal_values(arg)
    return values


def is_optional(annotation: Any) -> bool:
    return type(None) in get_args(annotation)


def doc_class_fields(node: ast.ClassDef) -> set[str]:
    return {
        statement.target.id
        for statement in node.body
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name)
    }


def ts_body(text: str, name: str) -> str | None:
    match = re.search(rf"export interface {name}\s*\{{(?P<body>.*?)\n\}}", text, re.DOTALL)
    return match.group("body") if match else None


def ts_fields(body: str) -> dict[str, bool]:
    """Returns {field: is_optional} for a TypeScript interface body."""
    return {
        match.group(1): bool(match.group(2))
        for match in re.finditer(r"^\s*([A-Za-z_][A-Za-z0-9_]*)(\?)?\s*:", body, re.MULTILINE)
    }


def assert_literals_in(label: str, values: set[str], target: str) -> None:
    for value in sorted(values):
        if f'"{value}"' not in target and f"'{value}'" not in target:
            fail(f"{label} is missing literal {value!r}")


def main() -> int:
    if not DOC_PATH.exists():
        fail(f"missing API spec: {DOC_PATH}")
    if not TS_PATH.exists():
        fail(f"missing frontend types: {TS_PATH}")
    if errors:
        return report()

    doc_text = DOC_PATH.read_text(encoding="utf-8")
    ts_text = TS_PATH.read_text(encoding="utf-8")

    if "## 4. Abstract Data Types" not in doc_text:
        fail("API spec section 4 is missing")
    try:
        doc_code = doc_text.split("~~~python", 1)[1].split("~~~", 1)[0]
        doc_tree = ast.parse(doc_code)
    except (IndexError, SyntaxError) as exc:
        fail(f"could not parse the ADT code block in {DOC_PATH}: {exc}")
        return report()

    doc_classes = {
        node.name: node for node in doc_tree.body if isinstance(node, ast.ClassDef)
    }
    models = pydantic_models()

    for name, model in sorted(models.items()):
        field_names = set(model.model_fields)
        literals: set[str] = set()
        optional_fields: set[str] = set()
        for field_name, field in model.model_fields.items():
            literals |= literal_values(field.annotation)
            if is_optional(field.annotation):
                optional_fields.add(field_name)

        doc_node = doc_classes.get(name)
        if doc_node is None:
            fail(f"API spec is missing Pydantic model {name}")
        else:
            documented = doc_class_fields(doc_node)
            missing = sorted(field_names - documented)
            extra = sorted(documented - field_names)
            if missing:
                fail(f"API spec {name} missing fields: {', '.join(missing)}")
            if extra:
                fail(f"API spec {name} has stale fields: {', '.join(extra)}")
            assert_literals_in(f"API spec {name}", literals, doc_code)

        if name in SHARED_TS_MODELS:
            body = ts_body(ts_text, name)
            if body is None:
                fail(f"frontend/src/types/cad.ts is missing interface {name}")
                continue
            declared = ts_fields(body)
            missing = sorted(field_names - set(declared))
            extra = sorted(set(declared) - field_names)
            if missing:
                fail(f"frontend {name} missing fields: {', '.join(missing)}")
            if extra:
                fail(f"frontend {name} has stale fields: {', '.join(extra)}")
            for field_name in sorted(optional_fields & set(declared)):
                if not declared[field_name]:
                    fail(f"frontend {name}.{field_name} should be optional")
            assert_literals_in(f"frontend {name}", literals, body)

    side_values = {member.value for member in adt.CaptureSide}
    side_node = doc_classes.get("CaptureSide")
    if side_node is None:
        fail("API spec is missing CaptureSide enum")
    else:
        doc_sides = {
            statement.value.value
            for statement in side_node.body
            if isinstance(statement, ast.Assign)
            and len(statement.targets) == 1
            and isinstance(statement.targets[0], ast.Name)
            and isinstance(statement.value, ast.Constant)
        }
        if doc_sides != side_values:
            fail(f"API spec CaptureSide drift: {sorted(doc_sides ^ side_values)}")
    axis_match = re.search(r"export type AxisView\s*=\s*(?P<union>[^;]+);", ts_text)
    if axis_match is None:
        fail("frontend AxisView union is missing")
    else:
        assert_literals_in("frontend AxisView", side_values, axis_match.group("union"))

    return report(len(models))


def report(model_count: int = 0) -> int:
    if errors:
        print("SCHEMA_SYNC_FAIL")
        for error in errors:
            print(f"- {error}")
        return 1
    print(
        f"SCHEMA_SYNC_OK: {model_count} Pydantic ADTs, "
        f"{len(SHARED_TS_MODELS)} shared TS interfaces"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
