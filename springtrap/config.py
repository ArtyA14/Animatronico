"""Configuración central. Todo se puede sobrescribir con variables de entorno."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOICES_DIR = ROOT / "voices"
MODELS_DIR = ROOT / "models"


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


def _env_opt(name: str) -> str | None:
    value = os.environ.get(name)
    return value or None


# --- LLM -------------------------------------------------------------------
OLLAMA_URL = _env("SPRINGTRAP_OLLAMA_URL", "http://127.0.0.1:11434")
LLM_MODEL = _env("SPRINGTRAP_LLM", "qwen3:4b-instruct-2507-q4_K_M")
LLM_NUM_CTX = int(_env("SPRINGTRAP_CTX", "6144"))
LLM_MAX_TOKENS = int(_env("SPRINGTRAP_MAX_TOKENS", "80"))
LLM_TEMPERATURE = float(_env("SPRINGTRAP_TEMP", "0.85"))
LLM_TOP_P = float(_env("SPRINGTRAP_TOP_P", "0.9"))
# 10 turnos de memoria: con 6, al llegar al mensaje 13 se recortaba el prefijo
# y Ollama perdía la caché del prompt (primer token de 0.07 s a 0.48 s).
LLM_HISTORY_TURNS = int(_env("SPRINGTRAP_HISTORY", "10"))
LLM_KEEP_ALIVE = _env("SPRINGTRAP_KEEP_ALIVE", "30m")

# Tope duro de caracteres hablados por turno. Es una red de seguridad para que
# el personaje no se enroque: 190 caracteres son ~32 palabras, unos 10 s de voz,
# en línea con la regla "unas 30 palabras" del prompt.
MAX_REPLY_CHARS = int(_env("SPRINGTRAP_MAX_CHARS", "190"))

# --- STT -------------------------------------------------------------------
STT_MODEL = _env("SPRINGTRAP_STT", "small")
STT_DEVICE = _env("SPRINGTRAP_STT_DEVICE", "auto")  # auto = GPU si se puede, si no CPU
STT_COMPUTE = _env("SPRINGTRAP_STT_COMPUTE", "int8")
STT_LANGUAGE = _env("SPRINGTRAP_LANG", "es")
STT_THREADS = int(_env("SPRINGTRAP_STT_THREADS", "8"))
STT_PROMPT = _env("SPRINGTRAP_STT_PROMPT", "")

# --- TTS -------------------------------------------------------------------
# Voz: Davefx Spanish Spain Medium (repositorio speaches-ai en Hugging Face)
# Ajustes para tono burlón y agudo sin ser chillón:
# - Pitch: -3.5 semitonos (más aguda que -2.0 default)
# - Length scale: 1.1 (ligeramente estirada para naturalidad)
# - Volume: 1.1 (ligeramente más fuerte para impactar)
VOICE_KEY = _env("SPRINGTRAP_VOICE", "es_ES-davefx-medium")
VOICE_PITCH_SEMITONES = float(_env("SPRINGTRAP_PITCH", "-3.5"))
VOICE_LENGTH_SCALE = float(_env("SPRINGTRAP_LENGTH_SCALE", "1.1"))
VOICE_VOLUME = float(_env("SPRINGTRAP_VOLUME", "1.1"))
# Pico al que normalizamos la señal. Piper por defecto satura a 1.0 y eso
# ensucia el audio (y confunde al STT): dejamos margen de cabeza.
VOICE_PEAK = float(_env("SPRINGTRAP_PEAK", "0.7"))

# --- Audio ---------------------------------------------------------------
MIC_SAMPLE_RATE = 16000

# --- Convert environment variable to int if numeric ---
def _parse_device_env(value: str | None) -> int | None:
    """Parse device env var: return int index if numeric, else return as string (name)."""
    if value is None:
        return None
    # Try to convert to int (device index)
    try:
        idx = int(value)
        # Verify it's a valid device index
        import sounddevice as sd
        if idx < 0 or idx >= len(sd.query_devices()):
            return value  # Out of range, treat as name
        return idx
    except (ValueError, TypeError):
        # Not a number, treat as device name
        return value

MIC_DEVICE = _parse_device_env(_env_opt("SPRINGTRAP_MIC"))
OUTPUT_DEVICE = _parse_device_env(_env_opt("SPRINGTRAP_OUTPUT"))

VAD_THRESHOLD_MIN = float(_env("SPRINGTRAP_VAD_MIN", "0.012"))
VAD_THRESHOLD_MAX = float(_env("SPRINGTRAP_VAD_MAX", "0.08"))
VAD_NOISE_MULT = float(_env("SPRINGTRAP_VAD_MULT", "4.0"))
VAD_SILENCE_S = float(_env("SPRINGTRAP_VAD_SILENCE", "0.6"))
VAD_MAX_UTTERANCE_S = float(_env("SPRINGTRAP_VAD_MAX", "14.0"))
VAD_START_TIMEOUT_S = float(_env("SPRINGTRAP_VAD_START", "10.0"))

# --- Mandíbula (SG90 en ESP32) ---------------------------------------------
JAW_ENABLED = _env("SPRINGTRAP_JAW", "0") == "1"
JAW_PORT = _env("SPRINGTRAP_JAW_PORT", "/dev/ttyUSB0")
JAW_BAUDRATE = int(_env("SPRINGTRAP_JAW_BAUD", "115200"))
JAW_MIN_ANGLE = int(_env("SPRINGTRAP_JAW_MIN", "10"))
JAW_MAX_ANGLE = int(_env("SPRINGTRAP_JAW_MAX", "60"))
JAW_FLOOR_DB = float(_env("SPRINGTRAP_JAW_FLOOR", "-45"))
JAW_CEIL_DB = float(_env("SPRINGTRAP_JAW_CEIL", "-12"))
JAW_GAMMA = float(_env("SPRINGTRAP_JAW_GAMMA", "0.7"))
JAW_ATTACK = float(_env("SPRINGTRAP_JAW_ATTACK", "0.6"))
JAW_RELEASE = float(_env("SPRINGTRAP_JAW_RELEASE", "0.15"))
JAW_SLEW = float(_env("SPRINGTRAP_JAW_SLEW", "700"))
JAW_DEADBAND = float(_env("SPRINGTRAP_JAW_DEADBAND", "2"))
JAW_HEARTBEAT_S = float(_env("SPRINGTRAP_JAW_HEARTBEAT", "0.75"))


def voice_paths(key: str = VOICE_KEY) -> tuple[Path, Path]:
    """Devuelve (modelo .onnx, config .onnx.json) de una voz Piper."""
    return VOICES_DIR / f"{key}.onnx", VOICES_DIR / f"{key}.onnx.json"
