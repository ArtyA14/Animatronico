"""Springtrap: pipeline de voz 100% local (STT -> LLM -> TTS).

El parche de PortAudio debe ejecutarse antes de importar ``sounddevice``,
por eso vive en el ``__init__`` del paquete: cualquier import de ``springtrap.*``
lo aplica automáticamente.
"""

from __future__ import annotations

import ctypes.util
import os
from pathlib import Path

__version__ = "0.1.0"


_AUDIO_LIB_DIRS = [
    Path.home() / ".local/opt/audio-libs/usr/lib/x86_64-linux-gnu",
    Path.home() / ".local/opt/audio-libs/usr/lib/x86_64-linux-gnu/pulseaudio",
]


def _preload_audio_libs() -> list[str]:
    """Carga libasound/libpulse/libjack en el proceso con RTLD_GLOBAL.

    PortAudio se enlaza dinámicamente contra ellas y en un WSL mínimo no
    están instaladas. Precargarlas permite que ``dlopen`` las resuelva sin
    necesitar sudo ni LD_LIBRARY_PATH.
    """
    if os.name != "posix":
        return []

    pending = [path for directory in _AUDIO_LIB_DIRS if directory.is_dir() for path in sorted(directory.glob("*.so*"))]

    # Varias pasadas: cada una resuelve las librerías cuyas dependencias ya
    # están cargadas. Con 2-3 pasadas queda todo el grafo en memoria.
    loaded: list[str] = []
    for _ in range(4):
        progress = False
        remaining = []
        for path in pending:
            try:
                ctypes.CDLL(str(path), mode=ctypes.RTLD_GLOBAL)
                loaded.append(str(path))
                progress = True
            except OSError:
                remaining.append(path)
        pending = remaining
        if not progress:
            break
    return loaded


def _configure_pulse() -> str | None:
    """En WSLg el servidor PulseAudio vive en /mnt/wslg/PulseServer."""
    if os.environ.get("PULSE_SERVER"):
        return os.environ["PULSE_SERVER"]
    socket = Path("/mnt/wslg/PulseServer")
    if socket.exists():
        os.environ["PULSE_SERVER"] = f"unix:{socket}"
        return os.environ["PULSE_SERVER"]
    return None


AUDIO_LIBS = _preload_audio_libs()
PULSE_SERVER = _configure_pulse()


def _patch_portaudio() -> str | None:
    """Hace que ``sounddevice`` encuentre libportaudio instalada en ~/.local.

    ``ctypes.util.find_library`` consulta la caché de ldconfig e ignora
    ``LD_LIBRARY_PATH``, así que si no hay una instalación de sistema
    devolvemos la ruta absoluta de la copia local.
    """
    if os.name != "posix":
        return None

    original = ctypes.util.find_library
    try:
        found = original("portaudio")
    except Exception:
        found = None
    if found:
        return found

    candidates = [
        Path(os.environ.get("PORTAUDIO_LIB", "")) if os.environ.get("PORTAUDIO_LIB") else None,
        Path.home() / ".local/opt/portaudio/usr/lib/x86_64-linux-gnu/libportaudio.so.2",
        Path("/usr/lib/x86_64-linux-gnu/libportaudio.so.2"),
        Path("/usr/lib/libportaudio.so.2"),
    ]
    for candidate in candidates:
        if candidate and candidate.exists():

            def patched(name: str, *args, **kwargs):
                if "portaudio" in name:
                    return str(candidate)
                return original(name, *args, **kwargs)

            ctypes.util.find_library = patched  # type: ignore[assignment]
            return str(candidate)

    return None


PORTAUDIO_PATH = _patch_portaudio()
