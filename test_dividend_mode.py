"""اختبار حماية الحساب المزدوج للتوزيعات: resolve_dividend_mode + CLI.
التشغيل: python test_dividend_mode.py   (أو pytest)
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from egx_4_mirrors_v3 import KNOWN_ADJUSTED_FOLDERS, resolve_dividend_mode

HERE = Path(__file__).parent


def _raises(folder: str, mode: str | None) -> str:
    try:
        resolve_dividend_mode(folder, mode)
    except ValueError as exc:
        return str(exc)
    raise AssertionError(f"expected ValueError for {folder!r} mode={mode!r}")


def test_known_folders_wrong_mode_fail() -> None:
    for name in KNOWN_ADJUSTED_FOLDERS:
        assert "must be 'none'" in _raises(str(HERE / name), "add")
    assert "must be 'add'" in _raises(str(HERE / "data"), "none")


def test_unknown_folder_needs_mode() -> None:
    assert "unknown data folder" in _raises("uploads", None)
    assert "unknown data folder" in _raises("C:/somewhere/else", None)
    assert "must be 'add' or 'none'" in _raises("uploads", "maybe")


def test_known_and_explicit_modes_work() -> None:
    assert resolve_dividend_mode(HERE / "data")[0] == "add"
    assert resolve_dividend_mode(HERE / "data", "add")[0] == "add"
    for name in KNOWN_ADJUSTED_FOLDERS:
        mode, line = resolve_dividend_mode(HERE / name)
        assert mode == "none" and "(adjusted, verified)" in line
    mode, line = resolve_dividend_mode("uploads", "none")
    assert mode == "none" and "unverified" in line


def test_cli_refuses_double_count() -> None:
    run = subprocess.run([sys.executable, str(HERE / "egx_4_mirrors_v3.py"), str(HERE / "data_2022_2023"),
                          "--backtest", "--dividend-mode", "add"], capture_output=True, text=True, cwd=HERE)
    assert run.returncode != 0 and "must be 'none'" in run.stderr


if __name__ == "__main__":
    for fn in [f for n, f in dict(globals()).items() if n.startswith("test_")]:
        fn()
        print("PASS", fn.__name__)
