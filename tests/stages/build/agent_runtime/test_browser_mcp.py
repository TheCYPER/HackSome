"""Account-browser wrapper argv construction (07-03-social-rail).

Locks the contract of agent/browser_mcp.sh — the agent's ONE browser, seeded
with the account's login state (2026-07-06 user decision: no incognito split).
Three INDEPENDENT graceful degradations, each pinned here by running the real
script against a fake playwright-mcp shim that echoes its argv:

  base           -> `--browser chromium` always first (load-bearing: the
                    container ships no branded chrome; dropping it bricks
                    every navigation).
  DISPLAY unset  -> `--headless` appended (headed is the playwright-mcp
                    default; with DISPLAY the browser runs on the kasm
                    desktop).
  cookies seed   -> $ACCOUNT_DIR/cookies/storage-state.json present appends
                    the `--isolated --storage-state <file>` PAIR (0.0.77:
                    storage-state applies to isolated sessions only; isolated
                    keeps the profile in memory = read-only seed, matching the
                    ro /account mount).
  CUA_PROXY set  -> `--proxy-server <url>` appended (all browser traffic rides
                    the account IP).

Missing any input is a legal state: the wrapper must still exec with the
remaining flags, never fail.
"""

import os
import stat
import subprocess

import pytest

from hacksome.stages.build import ASSETS_ROOT


WRAPPER = str(ASSETS_ROOT / "scripts" / "browser_mcp.sh")

SHIM = "#!/usr/bin/env bash\nprintf '%s\\n' \"$@\"\n"


@pytest.fixture
def run_wrapper(tmp_path):
    """Return a callable running the wrapper with a shimmed playwright-mcp.

    The shim sits first on PATH and prints one argv element per line, so each
    case asserts the EXACT argv the wrapper would exec. ACCOUNT_DIR defaults
    to an (empty) tmp dir — cases opt in to the cookies file by creating it.
    """
    shim_dir = tmp_path / "bin"
    shim_dir.mkdir()
    shim = shim_dir / "playwright-mcp"
    shim.write_text(SHIM)
    shim.chmod(shim.stat().st_mode | stat.S_IXUSR)
    account_dir = tmp_path / "account"
    account_dir.mkdir()

    def run(cookies=False, proxy=None, display=None):
        if cookies:
            (account_dir / "cookies").mkdir(exist_ok=True)
            (account_dir / "cookies" / "storage-state.json").write_text("{}")
        env = {
            "PATH": f"{shim_dir}:{os.environ['PATH']}",
            "ACCOUNT_DIR": str(account_dir),
        }
        if proxy is not None:
            env["CUA_PROXY"] = proxy
        if display is not None:
            env["DISPLAY"] = display
        out = subprocess.run(
            ["bash", WRAPPER], env=env, capture_output=True, text=True,
            check=True,
        ).stdout
        return out.splitlines()

    run.storage_state = str(account_dir / "cookies" / "storage-state.json")
    return run


def test_bare_container_headless_no_seed_no_proxy(run_wrapper):
    # No DISPLAY, no cookies, no proxy: behavior ≈ the pre-wrapper json args.
    assert run_wrapper() == ["--browser", "chromium", "--headless"]


def test_cookies_seed_adds_isolated_storage_state_pair(run_wrapper):
    assert run_wrapper(cookies=True) == [
        "--browser", "chromium", "--headless",
        "--isolated", "--storage-state", run_wrapper.storage_state,
    ]


def test_proxy_adds_proxy_server(run_wrapper):
    url = "http://user:pass@203.0.113.7:8080"
    assert run_wrapper(proxy=url) == [
        "--browser", "chromium", "--headless", "--proxy-server", url,
    ]


def test_cookies_and_proxy_compose(run_wrapper):
    url = "http://203.0.113.7:8080"
    assert run_wrapper(cookies=True, proxy=url) == [
        "--browser", "chromium", "--headless",
        "--isolated", "--storage-state", run_wrapper.storage_state,
        "--proxy-server", url,
    ]


def test_display_drops_headless_keeps_everything_else(run_wrapper):
    # On the kasm desktop (DISPLAY set) the browser runs headed — VNC
    # observable, better anti-bot fingerprint.
    url = "http://203.0.113.7:8080"
    argv = run_wrapper(cookies=True, proxy=url, display=":1")
    assert "--headless" not in argv
    assert argv == [
        "--browser", "chromium",
        "--isolated", "--storage-state", run_wrapper.storage_state,
        "--proxy-server", url,
    ]


def test_empty_display_and_empty_proxy_mean_unset(run_wrapper):
    # env_file-injected empties must degrade the same as absent vars.
    assert run_wrapper(proxy="", display="") == [
        "--browser", "chromium", "--headless",
    ]
