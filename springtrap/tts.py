"""Síntesis de voz local con Piper + un toque de pitch para sonar a Springtrap."""

from __future__ import annotations

import re

import numpy as np

from . import config

# Caracteres que no se pronuncian y solo estorban al sintetizador.
_CHARS = re.compile(r"[*_`#~|<>\[\]{}]")
_EMOJI = re.compile("[\U0001f000-\U0001faff\u2600-\u27bf\ufe0f]")
_SPACES = re.compile(r"\s+")


def clean_text(text: str) -> str:
    """Deja solo texto pronunciable."""
    text = _CHARS.sub("", text)
    text = _EMOJI.sub("", text)
    text = text.replace("—", ",").replace("–", ",")
    text = _SPACES.sub(" ", text)
    return text.strip()


def pitch_shift(audio: np.ndarray, semitones: float) -> np.ndarray:
    """Baja el tono remuestreando (más lento y más grave).

    Es un remuestreo lineal: introduce algo de aliasing, que aquí suma
    aspereza metálica. Para un animatrónico es una ventaja, no un defecto.
    """
    ratio = 2.0 ** (semitones / 12.0)
    if abs(ratio - 1.0) < 1e-3 or len(audio) < 2:
        return audio
    out_len = int(round(len(audio) / ratio))
    source = np.arange(len(audio), dtype=np.float64)
    target = np.linspace(0, len(audio) - 1, out_len, dtype=np.float64)
    return np.interp(target, source, audio).astype(np.float32)


class Voice:
    def __init__(
        self,
        key: str = config.VOICE_KEY,
        pitch_semitones: float = config.VOICE_PITCH_SEMITONES,
        length_scale: float = config.VOICE_LENGTH_SCALE,
        volume: float = config.VOICE_VOLUME,
    ) -> None:
        self.key = key
        self.model_path, self.config_path = config.voice_paths(key)
        self.pitch_semitones = pitch_semitones
        self.volume = volume
        self._voice = None
        self.sample_rate: int | None = None

        # Compensamos la duración que añade el pitch shift generando la voz
        # más rápida por el mismo factor: tono más grave, misma duración.
        pitch_ratio = 2.0 ** (pitch_semitones / 12.0)
        self.length_scale = length_scale * pitch_ratio

    def load(self) -> None:
        from piper import PiperVoice

        if not self.model_path.exists():
            raise FileNotFoundError(
                f"No encuentro la voz en {self.model_path}. "
                "Ejecuta: python scripts/download_voice.py"
            )
        self._voice = PiperVoice.load(self.model_path, self.config_path)
        self.sample_rate = self._voice.config.sample_rate

    def synthesize(self, text: str) -> np.ndarray:
        """Devuelve audio float32 mono a ``self.sample_rate``."""
        from piper import SynthesisConfig

        text = clean_text(text)
        if not text:
            return np.zeros(0, dtype=np.float32)

        if self._voice is None:
            self.load()

        synth_config = SynthesisConfig(
            length_scale=self.length_scale,
            noise_scale=0.667,
            noise_w_scale=0.8,
            volume=self.volume,
            normalize_audio=False,
        )

        chunks: list[np.ndarray] = []
        for chunk in self._voice.synthesize(text, synth_config):
            chunks.append(np.asarray(chunk.audio_float_array, dtype=np.float32).reshape(-1))

        if not chunks:
            return np.zeros(0, dtype=np.float32)

        audio = np.concatenate(chunks)
        if self.pitch_semitones:
            audio = pitch_shift(audio, self.pitch_semitones)

        # Normalizamos a un pico con margen: evita saturación en el altavoz y
        # mantiene el volumen constante entre frases.
        peak = float(np.abs(audio).max()) if audio.size else 0.0
        if peak > 1e-6 and config.VOICE_PEAK > 0:
            audio = audio * (config.VOICE_PEAK / peak)

        return audio.astype(np.float32)

    def preview(self, text: str) -> np.ndarray:
        """Sintetiza sin cargar el modelo dos veces (alias legible)."""
        return self.synthesize(text)
