"""Tests for ``apiome browse open PATH`` (CLI 9.9, #3252) and :mod:`apiome_cli.browse_url`.

No real browser is ever launched: the command's ``webbrowser.get`` is replaced by a recorder.
"""

from __future__ import annotations

import json
import webbrowser
from pathlib import Path

import pytest
from typer.testing import CliRunner

from apiome_cli import config as config_module
from apiome_cli.browse_url import (
    BrowseUrlError,
    build_browse_url,
    derive_browse_base,
    normalize_base,
    read_browse_section,
    resolve_browse_base,
)
from apiome_cli.commands import browse as browse_command
from apiome_cli.exit_codes import EXIT_ERROR, EXIT_SUCCESS, EXIT_USAGE
from apiome_cli.main import app

runner = CliRunner()
_BROWSE = "https://browse.apiome.dev"


class _Recorder:
    """Stands in for a ``webbrowser`` controller; records what it was asked to open."""

    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.opened: list[str] = []
        self.names: list[str | None] = []

    def get(self, name: str | None = None) -> _Recorder:
        if name == "nosuchbrowser":
            raise webbrowser.Error("could not locate runnable browser")
        self.names.append(name)
        return self

    def open(self, url: str) -> bool:
        self.opened.append(url)
        return self.result


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    """Replace the browser launcher and point the CLI at the production-style API host."""
    rec = _Recorder()
    monkeypatch.setattr(browse_command.webbrowser, "get", rec.get)
    monkeypatch.setenv("APIOME_BASE_URL", "https://api.apiome.dev")
    monkeypatch.delenv("APIOME_BROWSE_URL", raising=False)
    return rec


# --- URL building ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("acme-corp", f"{_BROWSE}/tenant/acme-corp"),
        ("acme-corp/payments-api", f"{_BROWSE}/tenant/acme-corp/payments-api"),
        ("acme-corp/payments-api/v2.1.0", f"{_BROWSE}/tenant/acme-corp/payments-api/v2.1.0"),
        (
            "acme-corp/payments-api/compare?v1=v2.0.0&v2=v2.1.0",
            f"{_BROWSE}/tenant/acme-corp/payments-api/compare?v1=v2.0.0&v2=v2.1.0",
        ),
        ("/acme-corp/payments-api/", f"{_BROWSE}/acme-corp/payments-api"),
        ("/mcp/search?q=pay", f"{_BROWSE}/mcp/search?q=pay"),
        (" acme corp/a#b ", f"{_BROWSE}/tenant/acme%20corp/a%23b"),
    ],
)
def test_build_browse_url(target: str, expected: str) -> None:
    """tenant / project / version / longer paths go under /tenant/; a leading / means the root."""
    assert build_browse_url(_BROWSE, target) == expected


@pytest.mark.parametrize("target", ["", "/", "acme-corp//v1", "?v1=a"])
def test_build_browse_url_rejects_empty_segments(target: str) -> None:
    """An empty path or an empty segment is a usage error."""
    with pytest.raises(BrowseUrlError, match="<tenant>"):
        build_browse_url(_BROWSE, target)


@pytest.mark.parametrize(
    ("api", "expected"),
    [
        ("https://api.apiome.dev", "https://browse.apiome.dev"),
        ("https://api.apiome.dev/v1/", "https://browse.apiome.dev"),
        ("https://api.example.com:8443", "https://browse.example.com:8443"),
        ("http://localhost:8000", "http://localhost:3001"),
        ("http://127.0.0.1:8000", "http://127.0.0.1:3001"),
        ("http://[::1]:8000", "http://[::1]:3001"),
    ],
)
def test_derive_browse_base(api: str, expected: str) -> None:
    """api.<domain> → browse.<domain>; a local API → the browse dev server on port 3001."""
    assert derive_browse_base(api) == expected


@pytest.mark.parametrize("api", ["https://apiome.example.com", "https://api."])
def test_derive_browse_base_explains_how_to_configure(api: str) -> None:
    """Hosts that match no rule say how to set the address."""
    with pytest.raises(BrowseUrlError, match=r"APIOME_BROWSE_URL.*\[browse\] url"):
        derive_browse_base(api)


def test_normalize_base() -> None:
    """A configured base must be absolute http(s); a trailing / is dropped."""
    assert normalize_base(" https://b.example.com/browse/ ", source="x") == "https://b.example.com/browse"
    with pytest.raises(BrowseUrlError, match="x must be an http"):
        normalize_base("browse.example.com", source="x")


def test_read_browse_section(tmp_path: Path) -> None:
    """[browse] url is read; a missing file, section or empty value is None; bad TOML raises."""
    path = tmp_path / "config.toml"
    assert read_browse_section(path) is None
    path.write_text('base_url = "https://api.x.dev"\n', encoding="utf-8")
    assert read_browse_section(path) is None
    path.write_text('[browse]\nurl = ""\n', encoding="utf-8")
    assert read_browse_section(path) is None
    path.write_text('[browse]\nurl = "https://docs.x.dev/browse"\n', encoding="utf-8")
    assert read_browse_section(path) == "https://docs.x.dev/browse"
    path.write_text("[browse]\nurl = 3\n", encoding="utf-8")
    with pytest.raises(BrowseUrlError, match="must be a string"):
        read_browse_section(path)
    path.write_text("[browse\n", encoding="utf-8")
    with pytest.raises(BrowseUrlError, match="Cannot read"):
        read_browse_section(path)


def test_resolve_browse_base_precedence(tmp_path: Path) -> None:
    """APIOME_BROWSE_URL beats [browse] url, which beats derivation from the API base."""
    path = tmp_path / "config.toml"
    path.write_text('[browse]\nurl = "https://cfg.example.com/"\n', encoding="utf-8")
    api = "https://api.apiome.dev"
    assert resolve_browse_base(env_value="https://env.example.com", config_path=path, api_base_url=api) == (
        "https://env.example.com"
    )
    assert resolve_browse_base(env_value=" ", config_path=path, api_base_url=api) == "https://cfg.example.com"
    assert resolve_browse_base(env_value=None, config_path=tmp_path / "none.toml", api_base_url=api) == _BROWSE


# --- command ---------------------------------------------------------------------------------


def test_opens_the_default_browser(recorder: _Recorder) -> None:
    """With no flags the URL opens in the default browser and the arrow line is printed."""
    result = runner.invoke(app, ["browse", "open", "acme-corp/payments-api/v2.1.0"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    url = f"{_BROWSE}/tenant/acme-corp/payments-api/v2.1.0"
    assert recorder.opened == [url]
    assert recorder.names == [None]
    assert result.stdout == f"→ Opening {url} …\n"


def test_print_url_never_launches(recorder: _Recorder) -> None:
    """--print-url prints only the URL (pipe-friendly) and opens nothing — the headless path."""
    result = runner.invoke(app, ["browse", "open", "acme-corp", "--print-url"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert result.stdout == f"{_BROWSE}/tenant/acme-corp\n"
    assert recorder.opened == []


def test_print_url_json(recorder: _Recorder) -> None:
    """Global --json with --print-url gives {url, opened: false}."""
    result = runner.invoke(app, ["--json", "browse", "open", "acme-corp/payments-api", "--print-url"])
    assert json.loads(result.stdout) == {"url": f"{_BROWSE}/tenant/acme-corp/payments-api", "opened": False}


def test_opened_json(recorder: _Recorder) -> None:
    """Global --json after a launch gives {url, opened: true}."""
    result = runner.invoke(app, ["--json", "browse", "open", "acme-corp"])
    assert json.loads(result.stdout) == {"url": f"{_BROWSE}/tenant/acme-corp", "opened": True}


def test_browser_flag_picks_the_browser(recorder: _Recorder) -> None:
    """--browser NAME asks webbrowser for that browser."""
    result = runner.invoke(app, ["browse", "open", "acme-corp", "--browser", "firefox"])
    assert result.exit_code == EXIT_SUCCESS, result.output
    assert recorder.names == ["firefox"]


def test_unknown_browser_exits_2(recorder: _Recorder) -> None:
    """A browser webbrowser does not know is a usage error."""
    result = runner.invoke(app, ["browse", "open", "acme-corp", "--browser", "nosuchbrowser"])
    assert result.exit_code == EXIT_USAGE
    assert "Unknown browser 'nosuchbrowser'" in result.stderr


def test_launch_failure_exits_1_and_suggests_print_url(recorder: _Recorder) -> None:
    """When no browser can be launched (no display), exit 1 and point at --print-url."""
    recorder.result = False
    result = runner.invoke(app, ["browse", "open", "acme-corp"])
    assert result.exit_code == EXIT_ERROR
    assert "Use --print-url" in result.stderr


def test_env_and_config_section_override_derivation(
    recorder: _Recorder, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """[browse] url in the user config is used; APIOME_BROWSE_URL overrides it."""
    path = tmp_path / "config.toml"
    path.write_text('[browse]\nurl = "https://specs.example.com/browse"\n', encoding="utf-8")
    monkeypatch.setattr(config_module, "user_config_path", lambda: path)
    result = runner.invoke(app, ["browse", "open", "acme-corp", "--print-url"])
    assert result.stdout == "https://specs.example.com/browse/tenant/acme-corp\n"
    monkeypatch.setenv("APIOME_BROWSE_URL", "http://localhost:4000")
    result = runner.invoke(app, ["browse", "open", "acme-corp", "--print-url"])
    assert result.stdout == "http://localhost:4000/tenant/acme-corp\n"


def test_base_url_flag_drives_derivation(recorder: _Recorder) -> None:
    """The global --base-url is the API base that derivation starts from."""
    result = runner.invoke(app, ["--base-url", "http://localhost:8000", "browse", "open", "acme-corp", "--print-url"])
    assert result.stdout == "http://localhost:3001/tenant/acme-corp\n"


@pytest.mark.parametrize(
    "args",
    [
        ["--base-url", "https://apiome.example.com", "browse", "open", "acme-corp"],
        ["browse", "open", "acme-corp//v1"],
    ],
)
def test_usage_errors_exit_2_without_launching(recorder: _Recorder, args: list[str]) -> None:
    """No derivable browse address, or a bad PATH, exits 2 and opens nothing."""
    result = runner.invoke(app, args)
    assert result.exit_code == EXIT_USAGE
    assert recorder.opened == []


def test_config_writes_keep_the_browse_section(tmp_path: Path) -> None:
    """`config set` rewrites the known keys but carries [browse] url over (never drops it)."""
    path = tmp_path / "config.toml"
    path.write_text('base_url = "http://x.dev"\n\n[browse]\nurl = "https://specs.example.com"\n', encoding="utf-8")
    config_module.write_user_config_file({"base_url": "https://api.y.dev"}, path=path)
    assert read_browse_section(path) == "https://specs.example.com"
    assert config_module.read_user_config_file(path) == {"base_url": "https://api.y.dev"}
    config_module.write_user_config_file({}, path=path)
    assert path.read_text(encoding="utf-8") == '[browse]\nurl = "https://specs.example.com"\n'
