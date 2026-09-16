#!/usr/bin/env python3
"""books.yaml / sectors.yaml read, validate and write-back (ARCHITECTURE.md §2 /config).

Three entry points, used in-process by backend/routes.py and from the CLI:

  load(desk_root)                  -> {"books":…, "sectors":…, "constraints":…}
  validate(books, sectors, desk_root) -> {"ok": bool, "errors": [...],
                                          "warnings": [...], "diff": "<unified>"}
  apply(books, sectors, desk_root)  -> validate first; only a passing config is
                                       written, atomically, to both YAML files.

validate() never touches the real files. It dumps the proposed config into a
throwaway desk tree -- <tmp>/books.yaml, <tmp>/sectors.yaml and a copy of
engine/validate_config.py, because that script resolves the desk root from its
own location -- and runs it there with the current interpreter.

WRITE-BACK LOSES YAML COMMENTS. Both files are heavily commented by hand and a
safe_load/safe_dump round trip keeps only the data. apply() therefore copies
each file to <name>.yaml.bak.<timestamp> in the desk root before overwriting,
which is the way back to the comments. Preserving them in place would need a
round-tripping YAML library, and PyYAML is the only third-party package allowed
here.

Requires PyYAML. No other third-party package.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import date as _date
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

def _default_desk_root() -> str:
    """``$DESK_ROOT``, else ``~/trading-desk`` — the desk tree is DATA, not code."""
    env = os.environ.get("DESK_ROOT", "").strip()
    return env or str(Path.home() / "trading-desk")


DEFAULT_DESK_ROOT = _default_desk_root()

BOOKS_NAME = "books.yaml"
SECTORS_NAME = "sectors.yaml"
VALIDATOR_REL = Path("engine") / "validate_config.py"

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: validate_config.py exit codes: 0 clean, 2 warnings only, 1 errors.
_EXIT_OK = (0, 2)

_VALIDATE_TIMEOUT_SECS = 60


class ConfigError(RuntimeError):
    """Raised when a write cannot proceed (validation failed, or files missing)."""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def resolve_desk_root(explicit: str | None = None) -> Path:
    """CLI flag wins, then $TRADING_DESK_ROOT / $DESK_ROOT, then the contract default."""
    raw = explicit or os.environ.get("TRADING_DESK_ROOT") or os.environ.get(
        "DESK_ROOT") or DEFAULT_DESK_ROOT
    return Path(raw).expanduser()


def dump_yaml(data: Any) -> str:
    """One canonical dump used for the temp desk, the diff and the write-back."""
    return yaml.safe_dump(_yamlable(data), sort_keys=False, allow_unicode=True,
                          default_flow_style=False, width=100)


def _jsonable(obj: Any) -> Any:
    """date / datetime values -> ISO strings, so the payload survives json.dumps.

    books.yaml carries `hard_expiry_date: 2026-06-01`, which PyYAML hands back
    as a datetime.date. Without this, GET /config raises on serialization.
    """
    if isinstance(obj, dict):
        return {key: _jsonable(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_jsonable(item) for item in obj]
    if isinstance(obj, (datetime, _date)):
        return obj.isoformat()
    return obj


def _yamlable(obj: Any) -> Any:
    """Inverse of _jsonable for values: a plain YYYY-MM-DD string -> date.

    Keeps a load -> edit -> apply round trip from silently retyping a YAML date
    into a quoted string. Only values are converted; keys are left alone.
    """
    if isinstance(obj, dict):
        return {key: _yamlable(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_yamlable(item) for item in obj]
    if isinstance(obj, str) and _ISO_DATE_RE.match(obj):
        try:
            return _date.fromisoformat(obj)
        except ValueError:
            return obj
    return obj


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise ConfigError(f"{path.name} not found at {path}")
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path.name}: top level must be a mapping")
    return data


def _atomic_write(path: Path, text: str) -> None:
    """Write via a same-directory temp file + os.replace, then fsync the dir."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent),
                                    prefix=f".{path.name}.", suffix=".tmp")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def _parse_validator_output(text: str) -> tuple[list[str], list[str]]:
    """Split the validator's stderr into (errors, warnings) by its section headers."""
    errors: list[str] = []
    warnings: list[str] = []
    bucket: list[str] | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if "ERROR(S)" in stripped:
            bucket = errors
            continue
        if "WARNING(S)" in stripped:
            bucket = warnings
            continue
        if stripped.startswith("•"):
            (bucket if bucket is not None else errors).append(
                stripped.lstrip("•").strip())
    return errors, warnings


# --------------------------------------------------------------------------- #
# load
# --------------------------------------------------------------------------- #
def load(desk_root: str | Path | None = None) -> dict[str, Any]:
    """Both YAML files as the §2 GET /config payload, JSON-safe."""
    root = resolve_desk_root(str(desk_root) if desk_root else None)
    books = _jsonable(_read_yaml(root / BOOKS_NAME))
    sectors = _jsonable(_read_yaml(root / SECTORS_NAME))
    return {"books": books, "sectors": sectors,
            "constraints": books.get("account_constraints")}


# --------------------------------------------------------------------------- #
# validate
# --------------------------------------------------------------------------- #
def build_diff(books: dict[str, Any], sectors: dict[str, Any],
               desk_root: Path) -> str:
    """Unified diff of what apply() would write, against the files on disk."""
    chunks: list[str] = []
    for name, proposed in ((BOOKS_NAME, books), (SECTORS_NAME, sectors)):
        path = desk_root / name
        current = path.read_text() if path.exists() else ""
        chunks.extend(difflib.unified_diff(
            current.splitlines(keepends=True),
            dump_yaml(proposed).splitlines(keepends=True),
            fromfile=f"a/{name}", tofile=f"b/{name}"))
    return "".join(chunks)


def validate(books: dict[str, Any], sectors: dict[str, Any],
             desk_root: str | Path | None = None) -> dict[str, Any]:
    """Run engine/validate_config.py against a proposed config. Writes nothing."""
    root = resolve_desk_root(str(desk_root) if desk_root else None)
    validator = root / VALIDATOR_REL
    if not validator.exists():
        return {"ok": False, "errors": [f"validator not found at {validator}"],
                "warnings": [], "diff": ""}
    if not isinstance(books, dict) or not isinstance(sectors, dict):
        return {"ok": False,
                "errors": ["books and sectors must both be mappings"],
                "warnings": [], "diff": ""}

    with tempfile.TemporaryDirectory(prefix="desk-config-validate-") as tmp:
        sandbox = Path(tmp)
        (sandbox / "engine").mkdir()
        shutil.copy2(validator, sandbox / VALIDATOR_REL)
        (sandbox / BOOKS_NAME).write_text(dump_yaml(books), encoding="utf-8")
        (sandbox / SECTORS_NAME).write_text(dump_yaml(sectors), encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, str(sandbox / VALIDATOR_REL)],
                capture_output=True, text=True, cwd=str(sandbox),
                timeout=_VALIDATE_TIMEOUT_SECS)
        except subprocess.TimeoutExpired:
            return {"ok": False,
                    "errors": [f"validate_config.py timed out after "
                               f"{_VALIDATE_TIMEOUT_SECS}s"],
                    "warnings": [], "diff": ""}

    errors, warnings = _parse_validator_output(proc.stderr)
    ok = proc.returncode in _EXIT_OK
    if not ok and not errors:
        errors = [f"validate_config.py exited {proc.returncode}: "
                  f"{(proc.stderr or proc.stdout).strip() or 'no output'}"]
    return {"ok": ok, "errors": errors, "warnings": warnings,
            "diff": build_diff(books, sectors, root)}


# --------------------------------------------------------------------------- #
# apply
# --------------------------------------------------------------------------- #
def apply(books: dict[str, Any], sectors: dict[str, Any],
          desk_root: str | Path | None = None,
          backup: bool = True) -> dict[str, Any]:
    """Validate, then atomically write both YAML files. A failing config is not written.

    Returns the validate() result plus "written" (the paths) and "backups".
    Raises ConfigError when validation fails, so a caller cannot write by accident.
    """
    root = resolve_desk_root(str(desk_root) if desk_root else None)
    result = validate(books, sectors, root)
    if not result["ok"]:
        raise ConfigError("config rejected; nothing written: "
                          + "; ".join(result["errors"]))

    stamp = time.strftime("%Y%m%dT%H%M%S")
    backups: list[str] = []
    written: list[str] = []
    for name, proposed in ((BOOKS_NAME, books), (SECTORS_NAME, sectors)):
        path = root / name
        if backup and path.exists():
            spare = path.with_name(f"{name}.bak.{stamp}")
            shutil.copy2(path, spare)
            backups.append(str(spare))
        _atomic_write(path, dump_yaml(proposed))
        written.append(str(path))

    return {**result, "written": written, "backups": backups}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _read_payload(path: str) -> dict[str, Any]:
    """Read a proposed config from a JSON or YAML file, or '-' for stdin."""
    text = sys.stdin.read() if path == "-" else Path(path).read_text()
    data = yaml.safe_load(text)  # a superset of JSON
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: expected a mapping at the top level")
    return data


def _payload_pair(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any]]:
    """--config FILE holds {"books":…, "sectors":…}; or pass --books and --sectors."""
    if args.config:
        bundle = _read_payload(args.config)
        missing = {"books", "sectors"} - set(bundle)
        if missing:
            raise ConfigError(f"{args.config}: missing key(s) {sorted(missing)}")
        return bundle["books"], bundle["sectors"]
    if not (args.books and args.sectors):
        raise ConfigError("pass --config FILE, or both --books FILE and "
                          "--sectors FILE")
    return _read_payload(args.books), _read_payload(args.sectors)


def cmd_load(args: argparse.Namespace) -> int:
    print(json.dumps(load(args.desk_root), ensure_ascii=False, indent=2))
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    books, sectors = _payload_pair(args)
    result = validate(books, sectors, args.desk_root)
    if args.diff_only:
        sys.stdout.write(result["diff"])
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


def cmd_apply(args: argparse.Namespace) -> int:
    books, sectors = _payload_pair(args)
    result = apply(books, sectors, args.desk_root, backup=not args.no_backup)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def _add_payload_args(sub: argparse.ArgumentParser) -> None:
    sub.add_argument("--config", metavar="FILE",
                     help='JSON/YAML holding {"books":…, "sectors":…}; - for stdin')
    sub.add_argument("--books", metavar="FILE", help="proposed books.yaml payload")
    sub.add_argument("--sectors", metavar="FILE",
                     help="proposed sectors.yaml payload")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="config_io.py",
        description="Read, validate and write back books.yaml / sectors.yaml.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               "  config_io.py load\n"
               "  config_io.py load | config_io.py validate --config -\n"
               "  config_io.py validate --config proposed.json --diff-only\n"
               "  config_io.py apply --config proposed.json\n")
    root_help = ("desk data root (default: $TRADING_DESK_ROOT, else "
                 f"{DEFAULT_DESK_ROOT})")
    sub = parser.add_subparsers(dest="command", required=True)

    load_cmd = sub.add_parser("load", help="print the GET /config payload")
    load_cmd.add_argument("--desk-root", metavar="PATH", help=root_help)
    load_cmd.set_defaults(func=cmd_load)

    validate_cmd = sub.add_parser(
        "validate", help="check a proposed config; writes nothing")
    _add_payload_args(validate_cmd)
    validate_cmd.add_argument("--diff-only", action="store_true",
                              help="print just the unified diff")
    validate_cmd.add_argument("--desk-root", metavar="PATH", help=root_help)
    validate_cmd.set_defaults(func=cmd_validate)

    apply_cmd = sub.add_parser(
        "apply", help="validate then write both YAML files atomically")
    _add_payload_args(apply_cmd)
    apply_cmd.add_argument("--no-backup", action="store_true",
                           help="skip the .bak copy (comments become unrecoverable)")
    apply_cmd.add_argument("--desk-root", metavar="PATH", help=root_help)
    apply_cmd.set_defaults(func=cmd_apply)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
