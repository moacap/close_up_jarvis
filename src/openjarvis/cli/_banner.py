"""Startup banner — Close-UP wordmark + tagline."""

from __future__ import annotations

_WORDMARK = "Close-UP"

_TAGLINE = "Personal AI, On Personal Devices"


def print_banner(quiet: bool = False) -> None:
    """Print the Close-UP startup banner. No-op when quiet."""
    if quiet:
        return
    try:
        from rich.console import Console

        console = Console()
        console.print(_WORDMARK, style="bold bright_blue", highlight=False, markup=False)
        console.print(_TAGLINE, style="cyan", highlight=False, markup=False)
        console.print()
    except ImportError:
        print(_WORDMARK)
        print(_TAGLINE)
        print()
