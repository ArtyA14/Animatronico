"""Arranque nativo: prepara las librerías que el sistema no encuentra solo.

Hay dos escenarios distintos:

* **WSL/Linux**: no hay `libasound`/`libpulse` instaladas en el sistema y no
  tenemos sudo. Están extraídas en ``~/.local/opt/audio-libs``; el *loader* de
  glibc solo las encuentra si ``LD_LIBRARY_PATH`` está definido **antes** de
  arrancar el proceso, así que nos reejecutamos una vez con el entorno
  corregido.
* **Windows**: CTranslate2 necesita cuDNN y cuBLAS. Los instalamos con pip en
  ``site-packages/nvidia/*/bin`` y se los anunciamos con
  ``os.add_dll_directory`` (el equivalente moderno a tocar el PATH).

Se llama al principio de ``main.py``, antes de importar nada pesado.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_MARKER = "SPRINGTRAP_NATIVE_READY"

# os.add_dll_directory devuelve un handle que hay que mantener vivo mientras se
# usen las DLLs; si se recolecta, Windows deja de encontrarlas.
_DLL_HANDLES: list = []

_LIB_DIRS = [
    Path.home() / ".local/opt/audio-libs/usr/lib/x86_64-linux-gnu",
    Path.home() / ".local/opt/audio-libs/usr/lib/x86_64-linux-gnu/pulseaudio",
    Path.home() / ".local/opt/portaudio/usr/lib/x86_64-linux-gnu",
]


def _cuda_lib_dirs() -> list[Path]:
    """Librerías CUDA instaladas por pip (cuDNN, cuBLAS) dentro del venv.

    CTranslate2 las busca por soname, así que tienen que estar en
    LD_LIBRARY_PATH igual que el resto.
    """
    site_packages = Path(sys.prefix) / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
    nvidia = site_packages / "nvidia"
    if not nvidia.is_dir():
        return []
    return sorted(path for path in nvidia.glob("*/lib") if path.is_dir())


def _windows_cuda_bin_dirs() -> list[Path]:
    """``site-packages\\nvidia\\*\\bin`` con las DLLs de cuDNN y cuBLAS."""
    site_packages = Path(sys.prefix) / "Lib" / "site-packages"
    nvidia = site_packages / "nvidia"
    if not nvidia.is_dir():
        return []
    return sorted(path for path in nvidia.glob("*/bin") if path.is_dir())


def ensure_cuda_windows() -> None:
    """Registra las DLLs de CUDA del venv para que CTranslate2 use la GPU.

    En Windows el cargador no mira LD_LIBRARY_PATH sino que cada directorio hay
    que anunciarlo explícitamente. Es idempotente: si ya se llamó, no hace nada.
    """
    if os.name != "nt" or _DLL_HANDLES:
        return

    for directory in _windows_cuda_bin_dirs():
        try:
            _DLL_HANDLES.append(os.add_dll_directory(str(directory)))
        except (OSError, AttributeError):
            continue


def ensure_native_libs() -> None:
    if os.name == "nt":
        ensure_cuda_windows()
        return

    if os.name != "posix" or os.environ.get(_MARKER) == "1":
        return

    directories = [str(path) for path in _LIB_DIRS if path.is_dir()]
    directories += [str(path) for path in _cuda_lib_dirs()]
    if not directories:
        return

    env = dict(os.environ)
    current = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = ":".join(directories + ([current] if current else []))
    env[_MARKER] = "1"

    if not env.get("PULSE_SERVER"):
        socket = Path("/mnt/wslg/PulseServer")
        if socket.exists():
            env["PULSE_SERVER"] = f"unix:{socket}"

    os.execve(sys.executable, [sys.executable, *sys.argv], env)
