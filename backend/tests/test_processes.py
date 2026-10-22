"""Programmes externes sous Windows (docs/apps/windows.md) : commandes des réglages, scripts
`.cmd` de npm lancés sans `cmd.exe`, aucune console visible, arrêt de l'arbre de processus."""

import asyncio
import subprocess
import sys
from pathlib import Path

import pytest

from app.core import processes
from app.tools.tab_mcp import TabMcpClient


def test_split_command_posix_and_windows(tmp_path: Path) -> None:
    assert processes.split_command("node /a/atelier-mcp.mjs", "darwin") == [
        "node",
        "/a/atelier-mcp.mjs",
    ]
    # Windows : barres obliques inverses gardées, guillemets autour d'un argument retirés
    command = r'"C:\Users\François\AppData\Local\Programs\nodejs\node.exe" "C:\dépôt\atelier tab\dist-desktop\atelier-mcp.mjs"'
    assert processes.split_command(command, "win32") == [
        r"C:\Users\François\AppData\Local\Programs\nodejs\node.exe",
        r"C:\dépôt\atelier tab\dist-desktop\atelier-mcp.mjs",
    ]
    # Guillemets simples (shlex.quote, commande copiée de macOS)
    assert processes.split_command(r"'C:\Program Files\py.exe' 'C:\a b\x.py' -v", "win32") == [
        r"C:\Program Files\py.exe",
        r"C:\a b\x.py",
        "-v",
    ]
    assert processes.split_command(r"C:\Atelier_Tab\resources\atelier-mcp.cmd", "win32") == [
        r"C:\Atelier_Tab\resources\atelier-mcp.cmd"
    ]
    # Un fichier existant est pris tel quel, espaces compris, même sans guillemets
    spaced = tmp_path / "Atelier Tab" / "atelier-mcp"
    spaced.parent.mkdir()
    spaced.write_text("")
    assert processes.split_command(str(spaced)) == [str(spaced)]
    assert processes.split_command("  ") == []


def test_tab_mcp_command_from_settings(tmp_path: Path) -> None:
    from app.core.config import Settings

    spaced = tmp_path / "Atelier Tab" / "atelier-mcp.cmd"
    spaced.parent.mkdir()
    spaced.write_text("")
    client = TabMcpClient.from_settings(Settings(tab_mcp_command=str(spaced)))
    assert client is not None and client.command == [str(spaced)]


def write_npm_shim(folder: Path, target: str) -> Path:
    """Shim de `npm install -g` (cmd-shim), tel qu'il est écrit sous Windows."""
    shim = folder / "claude.cmd"
    shim.write_text(
        "@ECHO off\r\nGOTO start\r\n:find_dp0\r\nSET dp0=%~dp0\r\nEXIT /b\r\n:start\r\n"
        "SETLOCAL\r\nCALL :find_dp0\r\n\r\n"
        'IF EXIST "%dp0%\\node.exe" (\r\n  SET "_prog=%dp0%\\node.exe"\r\n) ELSE (\r\n'
        '  SET "_prog=node"\r\n  SET PATHEXT=%PATHEXT:;.JS;=;%\r\n)\r\n\r\n'
        "endLocal & goto #_undefined_# 2>NUL || title %COMSPEC% & "
        f'"%_prog%"  "%dp0%\\{target}" %*\r\n',
        encoding="utf-8",
    )
    return shim


def test_npm_shim_runs_node_directly(tmp_path: Path) -> None:
    """Arguments (prompt système, schéma JSON) jamais réinterprétés par cmd.exe."""
    target = tmp_path / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
    target.parent.mkdir(parents=True)
    target.write_text("")
    shim = write_npm_shim(tmp_path, r"node_modules\@anthropic-ai\claude-code\cli.js")
    # node.exe absent du dossier : celui du PATH
    assert processes.resolve_cmd_shim(shim, which=lambda _: "C:/nodejs/node.exe") == [
        "C:/nodejs/node.exe",
        str(target),
    ]
    (tmp_path / "node.exe").write_text("")
    direct = processes.windows_command([str(shim), "-p", 'a "b" & c %PATH%'], "win32")
    assert direct == [str(tmp_path / "node.exe"), str(target), "-p", 'a "b" & c %PATH%']
    # Hors Windows, ou script inconnu : inchangé
    assert processes.windows_command([str(shim), "x"], "darwin") == [str(shim), "x"]
    other = tmp_path / "autre.cmd"
    other.write_text("@echo off\r\nnode serveur.mjs\r\n")
    assert processes.windows_command([str(other)], "win32") == [str(other)]
    assert processes.is_batch(str(other)) and not processes.is_batch("claude.exe")


def test_npm_cmd_of_nodejs(tmp_path: Path) -> None:
    """`npm.cmd` de Node.js : `node.exe node_modules\\npm\\bin\\npm-cli.js`."""
    cli = tmp_path / "node_modules" / "npm" / "bin" / "npm-cli.js"
    cli.parent.mkdir(parents=True)
    cli.write_text("")
    (tmp_path / "node.exe").write_text("")
    npm = tmp_path / "npm.cmd"
    npm.write_text("@ECHO OFF\r\n")
    assert processes.windows_command([str(npm), "ci"], "win32") == [
        str(tmp_path / "node.exe"),
        str(cli),
        "ci",
    ]


def test_no_window_flag() -> None:
    if sys.platform == "win32":
        assert processes.NO_WINDOW == subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    else:
        assert processes.NO_WINDOW == 0  # sans effet ailleurs


@pytest.mark.skipif(sys.platform != "win32", reason="cmd.exe")
async def test_tab_mcp_through_cmd_script(tmp_path: Path) -> None:
    """Sous Windows, un serveur MCP lancé par un script `.cmd` répond, puis s'arrête."""
    fake = Path(__file__).parent / "fake_tab_mcp.py"
    script = tmp_path / "Atelier Tab" / "atelier-mcp.cmd"
    script.parent.mkdir()
    script.write_text(f'@"{sys.executable}" "{fake}" %*\r\n', encoding="utf-8")
    client = TabMcpClient([str(script)], data_dir=str(tmp_path / "data"), timeout=20)
    try:
        assert "set_cells" in await client.list_tools()
    finally:
        await asyncio.wait_for(client.aclose(), timeout=20)
