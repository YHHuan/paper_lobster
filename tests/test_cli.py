"""Smoke tests for lobster.cli — placeholder chat mode must not raise."""
from __future__ import annotations

from lobster.cli import main


def test_main_chat_returns_zero(capsys):
    assert main(["chat"]) == 0
    captured = capsys.readouterr()
    assert "lobster v4" in captured.out.lower()


def test_main_default_falls_back_to_chat(capsys):
    # No subcommand -> argparse sets cmd=None -> dispatcher routes to 'chat'.
    assert main([]) == 0
