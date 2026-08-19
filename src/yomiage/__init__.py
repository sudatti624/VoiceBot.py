from __future__ import annotations

from importlib import import_module


def main() -> None:
    import_module("yomiage.main").main()

__all__ = ["main"]
