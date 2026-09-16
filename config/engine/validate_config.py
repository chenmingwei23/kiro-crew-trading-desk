#!/usr/bin/env python3
"""Validate a desk root's books.yaml and sectors.yaml.

This is the gate in front of every config write. ``POST /config/apply`` runs it
against the PROPOSED config in a sandbox first and refuses to write when it fails,
so a bad edit made through the app never reaches your real files.

It belongs to the DESK ROOT, not to the app: it encodes your desk's rules, and you
are meant to add to it. Copy it in with the rest of the scaffold:

    mkdir -p "$DESK_ROOT/engine"
    cp config/engine/validate_config.py "$DESK_ROOT/engine/"

Run it directly against the files in the current directory:

    cd "$DESK_ROOT" && python3 engine/validate_config.py

The app depends on three things about this file, so keep them if you rewrite it:

* it reads ``books.yaml`` and ``sectors.yaml`` from the CURRENT DIRECTORY, with no
  arguments -- the sandbox copy is run with cwd set to a temp tree;
* findings go to STDERR under a line containing ``ERROR(S)`` or ``WARNING(S)``, one
  per line, each starting with ``•``;
* exit 0 for clean, 2 for warnings only, 1 for errors. Only 0 and 2 let a write
  through.

Without this file the app degrades honestly rather than silently: ``/config``
still reads and diffs, and apply refuses with "validator not found".
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover - the desk cannot be validated without it
    print("validate_config.py needs PyYAML (pip install pyyaml)", file=sys.stderr)
    raise SystemExit(1)

DESK = Path(__file__).resolve().parent.parent

#: What a book may say its stops are defined against. Extend this when you add a
#: style your risk reviewers know how to apply -- an unrecognised value is refused
#: rather than passed through, so a typo cannot reach a live book.
STOP_LOSS_STYLES = {"fundamental", "technical", "time", "volatility", "none"}

ERRORS: list[str] = []
WARNINGS: list[str] = []


def err(msg: str) -> None:
    ERRORS.append(msg)


def warn(msg: str) -> None:
    WARNINGS.append(msg)


def load(name: str) -> dict:
    """Parse one YAML file from the current directory. A failure is an error, not a crash."""
    path = Path(name)
    if not path.is_file():
        err(f"{name}: not found")
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        err(f"{name}: not valid YAML -- {exc}")
        return {}
    if data is None:
        err(f"{name}: empty")
        return {}
    if not isinstance(data, dict):
        err(f"{name}: top level must be a mapping")
        return {}
    return data


def check_sectors(sectors: dict) -> dict:
    """Pod definitions. Returns the pod map so books can be checked against it."""
    pods = sectors.get("sectors")
    if not isinstance(pods, dict) or not pods:
        err("sectors.yaml: needs a non-empty 'sectors' mapping")
        return {}

    seen_tickers: dict[str, str] = {}
    for pod, cfg in pods.items():
        at = f"sectors.yaml: sectors.{pod}"
        if not isinstance(cfg, dict):
            err(f"{at} must be a mapping")
            continue

        tickers = cfg.get("tickers")
        if not isinstance(tickers, list) or not tickers:
            # The one rule the app's own tests pin: a pod with no coverage produces
            # no research, so the daily chain would report it complete having done
            # nothing.
            err(f"{at}.tickers must be a non-empty list")
        else:
            for ticker in tickers:
                name = str(ticker)
                if not name.isupper() or not name.replace(".", "").replace("-", "").isalnum():
                    warn(f"{at}.tickers: {name!r} does not look like a ticker symbol")
                if name in seen_tickers and seen_tickers[name] != pod:
                    # Not fatal, but two pods researching one name means two
                    # conclusions on it and no rule for which one the desk acts on.
                    warn(f"{at}.tickers: {name} is also covered by "
                         f"{seen_tickers[name]}")
                seen_tickers.setdefault(name, str(pod))

        copies = cfg.get("analyst_copies", 1)
        if not isinstance(copies, int) or copies < 1:
            err(f"{at}.analyst_copies must be a positive integer")
        elif copies > 4:
            warn(f"{at}.analyst_copies is {copies}: that is {copies} independent runs "
                 "per analyst role per ticker, per round")

    return pods


def check_books(books: dict, pods: dict) -> None:
    book_map = books.get("books")
    if not isinstance(book_map, dict) or not book_map:
        err("books.yaml: needs a non-empty 'books' mapping")
        return

    for name, cfg in book_map.items():
        at = f"books.yaml: books.{name}"
        if not isinstance(cfg, dict):
            err(f"{at} must be a mapping")
            continue

        nav = cfg.get("nav_usd")
        if not isinstance(nav, (int, float)) or nav <= 0:
            err(f"{at}.nav_usd must be a positive number -- position sizing reads it")

        drawdown = cfg.get("max_drawdown_pct")
        if drawdown is not None:
            if not isinstance(drawdown, (int, float)) or not 0 < drawdown <= 100:
                err(f"{at}.max_drawdown_pct must be a percentage between 0 and 100")

        low = cfg.get("horizon_days_min")
        high = cfg.get("horizon_days_max")
        if isinstance(low, int) and isinstance(high, int) and low > high:
            err(f"{at}: horizon_days_min ({low}) is above horizon_days_max ({high})")

        instruments = cfg.get("instruments_allowed")
        if instruments is not None and (not isinstance(instruments, list) or not instruments):
            err(f"{at}.instruments_allowed must be a non-empty list when present")

        # A stop has to be defined against something measurable. A book whose stop
        # style is unrecognised gives the risk reviewers no rule to apply, and they
        # would each invent their own.
        style = cfg.get("stop_loss_style")
        if style is not None and str(style) not in STOP_LOSS_STYLES:
            err(f"{at}.stop_loss_style is {style!r}; expected one of "
                f"{', '.join(sorted(STOP_LOSS_STYLES))}")

        weights = cfg.get("pod_weights")
        if weights is not None:
            if not isinstance(weights, dict):
                err(f"{at}.pod_weights must be a mapping of pod to percentage")
            else:
                for pod in weights:
                    if pods and pod not in pods:
                        err(f"{at}.pod_weights names {pod!r}, which is not a pod in "
                            "sectors.yaml")
                total = sum(v for v in weights.values() if isinstance(v, (int, float)))
                if weights and abs(total - 100) > 0.01:
                    warn(f"{at}.pod_weights sums to {total}, not 100")

    # Every pod should be able to say which book it trades against.
    for pod, cfg in (pods or {}).items():
        book = (cfg or {}).get("book") if isinstance(cfg, dict) else None
        if book and book not in book_map:
            err(f"sectors.yaml: sectors.{pod}.book names {book!r}, which is not a book "
                "in books.yaml")


def check_constraints(books: dict) -> None:
    constraints = books.get("account_constraints")
    if constraints is None:
        warn("books.yaml: no account_constraints -- nothing bounds what a pod may "
             "propose")
        return
    if not isinstance(constraints, dict):
        err("books.yaml: account_constraints must be a mapping")
        return

    for key in ("max_position_pct_of_nav", "cash_buffer_pct",
                "max_single_book_drawdown_pct"):
        value = constraints.get(key)
        if value is not None and (not isinstance(value, (int, float))
                                  or not 0 <= value <= 100):
            err(f"books.yaml: account_constraints.{key} must be a percentage "
                "between 0 and 100")

    orders = constraints.get("allowed_option_orders")
    if orders is not None and not isinstance(orders, list):
        err("books.yaml: account_constraints.allowed_option_orders must be a list")

    # A broker that permits no leg-selling cannot execute a spread; saying both is
    # a config that describes an account nobody has.
    if constraints.get("spreads_executable") and not constraints.get(
            "can_sell_or_write_a_leg", True):
        err("books.yaml: account_constraints says spreads are executable but no leg "
            "may be sold or written -- a spread needs a short leg")


def main() -> int:
    sectors = load("sectors.yaml")
    books = load("books.yaml")
    pods = check_sectors(sectors) if sectors else {}
    if books:
        check_books(books, pods)
        check_constraints(books)

    if ERRORS:
        print(f"{len(ERRORS)} ERROR(S)", file=sys.stderr)
        for message in ERRORS:
            print(f"• {message}", file=sys.stderr)
    if WARNINGS:
        print(f"{len(WARNINGS)} WARNING(S)", file=sys.stderr)
        for message in WARNINGS:
            print(f"• {message}", file=sys.stderr)

    if ERRORS:
        return 1
    if WARNINGS:
        return 2
    print("config OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
