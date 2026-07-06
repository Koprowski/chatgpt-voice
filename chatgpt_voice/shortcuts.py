"""Windows shortcut installation helpers."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys


def settings_icon_path() -> Path:
    """Return the generated CV settings icon path."""
    from .config import config_dir

    icon_path = config_dir() / "settings.ico"
    icon_path.parent.mkdir(parents=True, exist_ok=True)
    _write_settings_icon(icon_path)
    return icon_path


def _write_settings_icon(path: Path) -> None:
    """Write a small CV monogram ICO using only the standard library."""
    import struct

    size = 32
    bg = (35, 78, 118)
    bg2 = (21, 51, 84)
    fg = (245, 248, 252)
    pixels: list[tuple[int, int, int, int]] = []
    for y in range(size):
        for x in range(size):
            inset = 1
            corner = 5
            left = x < inset
            right = x >= size - inset
            top = y < inset
            bottom = y >= size - inset
            corner_cut = (
                (x < corner and y < corner and (corner - x) + (corner - y) > corner + 1)
                or (x >= size - corner and y < corner and (x - (size - corner - 1)) + (corner - y) > corner + 1)
                or (x < corner and y >= size - corner and (corner - x) + (y - (size - corner - 1)) > corner + 1)
                or (x >= size - corner and y >= size - corner and (x - (size - corner - 1)) + (y - (size - corner - 1)) > corner + 1)
            )
            if left or right or top or bottom or corner_cut:
                pixels.append((0, 0, 0, 0))
                continue
            shade = (y * 18) // size
            color = (
                max(bg2[0], bg[0] - shade),
                max(bg2[1], bg[1] - shade),
                max(bg2[2], bg[2] - shade),
            )
            pixels.append((color[2], color[1], color[0], 255))

    def draw_pattern(pattern: list[str], offset_x: int, offset_y: int, scale: int = 3) -> None:
        for row, line in enumerate(pattern):
            for col, value in enumerate(line):
                if value != "1":
                    continue
                for dy in range(scale):
                    for dx in range(scale):
                        px = offset_x + col * scale + dx
                        py = offset_y + row * scale + dy
                        if 0 <= px < size and 0 <= py < size:
                            pixels[py * size + px] = (fg[2], fg[1], fg[0], 255)

    draw_pattern([
        "01110",
        "10001",
        "10000",
        "10000",
        "10000",
        "10001",
        "01110",
    ], 2, 6)
    draw_pattern([
        "10001",
        "10001",
        "10001",
        "01010",
        "01010",
        "00100",
        "00100",
    ], 16, 6)

    xor_bitmap = bytearray()
    for row in range(size - 1, -1, -1):
        for col in range(size):
            xor_bitmap.extend(pixels[row * size + col])

    and_mask = bytes(size * 4)
    bitmap_header = struct.pack(
        "<IIIHHIIIIII",
        40,
        size,
        size * 2,
        1,
        32,
        0,
        len(xor_bitmap) + len(and_mask),
        0,
        0,
        0,
        0,
    )
    image = bitmap_header + bytes(xor_bitmap) + and_mask
    icon_dir = struct.pack("<HHH", 0, 1, 1)
    icon_entry = struct.pack(
        "<BBBBHHII",
        size,
        size,
        0,
        0,
        1,
        32,
        len(image),
        6 + 16,
    )
    path.write_bytes(icon_dir + icon_entry + image)


def _pythonw_path() -> Path:
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe":
        candidate = exe.with_name("pythonw.exe")
        if candidate.exists():
            return candidate
    return exe


def install_windows_shortcuts() -> list[Path]:
    """Create Desktop and Start Menu shortcuts for the control panel."""
    if sys.platform != "win32":
        raise RuntimeError("Shortcut installation is only supported on Windows.")

    workdir = Path(__file__).resolve().parents[1]
    pythonw = _pythonw_path()
    restart_script = workdir / "restart.ps1"
    icon_path = settings_icon_path()

    env = {
        **os.environ,
        "CGV_PYTHONW": str(pythonw),
        "CGV_WORKDIR": str(workdir),
        "CGV_RESTART": str(restart_script),
        "CGV_ICON": str(icon_path),
    }
    script = r"""
$ErrorActionPreference = "Stop"
$desktop = [Environment]::GetFolderPath("Desktop")
$programs = [Environment]::GetFolderPath("Programs")
$startup = [Environment]::GetFolderPath("Startup")
$startMenu = Join-Path $programs "ChatGPT Voice"
New-Item -ItemType Directory -Path $startMenu -Force | Out-Null

function New-Shortcut($path, $target, $arguments, $description) {
    $wscript = New-Object -ComObject WScript.Shell
    $shortcut = $wscript.CreateShortcut($path)
    $shortcut.TargetPath = $target
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $env:CGV_WORKDIR
    $shortcut.Description = $description
    $shortcut.IconLocation = [Environment]::ExpandEnvironmentVariables($env:CGV_ICON)
    $shortcut.Save()
    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($shortcut) | Out-Null
    [System.Runtime.Interopservices.Marshal]::ReleaseComObject($wscript) | Out-Null
}

$desktopShortcut = Join-Path $desktop "ChatGPT Voice.lnk"
New-Shortcut $desktopShortcut $env:CGV_PYTHONW "-m chatgpt_voice settings" "Open ChatGPT Voice settings and launcher"

$settingsShortcut = Join-Path $startMenu "ChatGPT Voice Settings.lnk"
New-Shortcut $settingsShortcut $env:CGV_PYTHONW "-m chatgpt_voice settings" "Open ChatGPT Voice settings and launcher"

$startShortcut = Join-Path $startMenu "Start ChatGPT Voice.lnk"
New-Shortcut $startShortcut $env:CGV_PYTHONW "-m chatgpt_voice start" "Start ChatGPT Voice daemon"

if (Test-Path $env:CGV_RESTART) {
    New-Shortcut (Join-Path $startMenu "Restart ChatGPT Voice.lnk") "powershell.exe" "-WindowStyle Hidden -ExecutionPolicy Bypass -File `"$env:CGV_RESTART`"" "Restart ChatGPT Voice daemon"
}

$legacyVisualizerShortcuts = @(
    (Join-Path $startup "ChatGPT Voice Visualizer.lnk"),
    (Join-Path $startMenu "ChatGPT Voice Visualizer.lnk")
)
foreach ($shortcut in $legacyVisualizerShortcuts) {
    if (Test-Path $shortcut) {
        Remove-Item $shortcut -Force
    }
}

Write-Output $desktopShortcut
Write-Output $settingsShortcut
Write-Output $startShortcut
"""
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    return [Path(line.strip()) for line in result.stdout.splitlines() if line.strip()]
