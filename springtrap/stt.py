"""Reconocimiento de voz local con faster-whisper.

El dispositivo por defecto es ``auto``: intenta GPU (float16) y, si falta
cualquier dependencia de CUDA, cae a CPU (int8) sin interrumpir la demo.
"""

from __future__ import annotations

import time

import numpy as np

from . import config


class Transcriber:
    def __init__(
        self,
        model_size: str = config.STT_MODEL,
        device: str = config.STT_DEVICE,
        compute_type: str = config.STT_COMPUTE,
        language: str = config.STT_LANGUAGE,
    ) -> None:
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.language = language
        self._model = None
        self.last_duration = 0.0
        self._fallbacks = 0

    # -- carga --------------------------------------------------------------
    def _build(self, device: str, compute_type: str):
        from faster_whisper import WhisperModel

        return WhisperModel(
            self.model_size,
            device=device,
            compute_type=compute_type,
            cpu_threads=config.STT_THREADS,
        )

    def load(self) -> float:
        """Carga el modelo (la primera vez descarga ~460 MB)."""
        started = time.perf_counter()

        if self.device == "auto":
            try:
                self._model = self._build("cuda", "float16")
                self.device = "cuda"
                self.compute_type = "float16"
            except Exception:
                self._model = self._build("cpu", "int8")
                self.device = "cpu"
                self.compute_type = "int8"
        else:
            self._model = self._build(self.device, self.compute_type)

        return time.perf_counter() - started

    # -- inferencia ---------------------------------------------------------
    def _run(self, audio: np.ndarray) -> str:
        assert self._model is not None
        segments, _info = self._model.transcribe(
            audio,
            language=self.language,
            beam_size=1,
            best_of=1,
            temperature=0.0,
            condition_on_previous_text=False,
            vad_filter=False,  # ya recortamos nosotros
            without_timestamps=True,
            initial_prompt=config.STT_PROMPT or None,
            no_speech_threshold=0.6,
        )
        return " ".join(segment.text.strip() for segment in segments).strip()

    def transcribe(self, audio: np.ndarray) -> str:
        """Transcribe audio float32 mono a 16 kHz."""
        if self._model is None:
            self.load()

        started = time.perf_counter()
        try:
            text = self._run(audio)
        except Exception:
            # CUDA puede fallar en la primera inferencia (memoria, cuDNN).
            # Reintentamos una sola vez en CPU en lugar de morir en directo.
            if self.device == "cpu" or self._fallbacks >= 1:
                raise
            self._fallbacks += 1
            self._model = self._build("cpu", "int8")
            self.device = "cpu"
            self.compute_type = "int8"
            text = self._run(audio)

        self.last_duration = time.perf_counter() - started
        return text
