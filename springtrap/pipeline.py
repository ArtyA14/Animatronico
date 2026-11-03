"""Orquestación: micrófono -> STT -> LLM -> TTS -> altavoz.

La idea central es no esperar a que el LLM termine: en cuanto suelta la primera
frase completa, se sintetiza y se encola para reproducir. Así el animatrónico
empieza a hablar mientras el modelo sigue generando.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

import numpy as np
from rich.console import Console

from . import config, persona
from .audio import Mic, Player
from .llm import Brain, BrainError
from .stt import Transcriber
from .tts import Voice

_SENTENCE_END = re.compile(r"(?<=[.!?…])\s+")
_CLAUSE_END = re.compile(r"(?<=[,;:])\s+")

console = Console()


class SentenceStream:
    """Acumula tokens y devuelve frases completas listas para TTS.

    ``min_chars`` alto evita mandar a Piper trozos como "Vivo." (0,4 s de audio),
    que son los que dejaban al reproductor sin datos entre frase y frase.
    """

    def __init__(self, min_chars: int = 30, max_chars: int = 180) -> None:
        self.min_chars = min_chars
        self.max_chars = max_chars
        self._buffer = ""

    def feed(self, text: str) -> list[str]:
        self._buffer += text
        parts = _SENTENCE_END.split(self._buffer)
        ready, self._buffer = parts[:-1], parts[-1]

        merged: list[str] = []
        for part in ready:
            part = part.strip()
            if not part:
                continue
            if merged and len(merged[-1]) < self.min_chars:
                merged[-1] = f"{merged[-1]} {part}"
            else:
                merged.append(part)

        # Frases kilométricas: las partimos por comas para no bloquear el TTS.
        final: list[str] = []
        for part in merged:
            if len(part) <= self.max_chars:
                final.append(part)
                continue
            clauses = _CLAUSE_END.split(part)
            current = ""
            for clause in clauses:
                if len(current) + len(clause) + 1 > self.max_chars and current:
                    final.append(current.strip())
                    current = clause
                else:
                    current = f"{current} {clause}".strip()
            if current:
                final.append(current)
        return final

    def flush(self) -> list[str]:
        rest = self._buffer.strip()
        self._buffer = ""
        return [rest] if rest else []


@dataclass
class Latency:
    stt_s: float = 0.0
    first_token_s: float = 0.0
    first_audio_s: float = 0.0
    total_s: float = 0.0
    chars: int = 0

    def summary(self) -> str:
        parts = []
        if self.stt_s:
            parts.append(f"STT {self.stt_s:.2f}s")
        parts.append(f"1er token {self.first_token_s:.2f}s")
        parts.append(f"1er audio {self.first_audio_s:.2f}s")
        parts.append(f"total {self.total_s:.2f}s")
        parts.append(f"{self.chars} car.")
        return " | ".join(parts)


class Springtrap:
    def __init__(
        self,
        brain: Brain | None = None,
        transcriber: Transcriber | None = None,
        voice: Voice | None = None,
        mic: Mic | None = None,
        on_level=None,
    ) -> None:
        self.brain = brain or Brain()
        self.transcriber = transcriber or Transcriber()
        self.voice = voice or Voice()
        self.mic = mic or Mic()
        self.player: Player | None = None
        self.jaw = None
        self._on_level = on_level
        self.last_latency = Latency()

    # -- ciclo de vida ------------------------------------------------------
    def warmup(self) -> None:
        with console.status("[yellow]Cargando voz..."):
            self.voice.load()
        with console.status(f"[yellow]Cargando {self.brain.model} en VRAM..."):
            seconds = self.brain.warmup()
        console.print(f"[green]LLM listo en {seconds:.1f}s[/green]")

        with console.status("[yellow]Cargando Whisper..."):
            seconds = self.transcriber.load()
        console.print(f"[green]STT listo en {seconds:.1f}s ({self.transcriber.device})[/green]")
        console.print(f"[dim]Micrófono: {self.mic.describe()}[/dim]")

        # Mandíbula: se engancha al mismo RMS que ya emite el Player.
        level_callback = self._on_level
        if config.JAW_ENABLED:
            try:
                from .jaw import Jaw

                self.jaw = Jaw()
                console.print(f"[green]Mandíbula lista en {config.JAW_PORT}[/green]")
            except Exception as exc:  # puerto ocupado, pyserial ausente, etc.
                self.jaw = None
                console.print(f"[yellow]Mandíbula desactivada: {exc}[/yellow]")

        if self.jaw is not None:
            jaw = self.jaw

            def level_callback(rms: float) -> None:
                jaw.update(rms)
                if self._on_level is not None:
                    self._on_level(rms)

        self.player = Player(
            samplerate=self.voice.sample_rate or 22050,
            on_level=level_callback,
        )
        self.player.start()

    def close(self) -> None:
        if self.player:
            self.player.close()
        if self.jaw is not None:
            self.jaw.close()
            self.jaw = None

    # -- habla --------------------------------------------------------------
    def say(self, text: str) -> None:
        """Dice algo sin pasar por el LLM (saludo, respaldo, despedida)."""
        assert self.player is not None, "Llama a warmup() antes de hablar"
        for sentence in SentenceStream().feed(text + " ") or [text]:
            self.player.play(self.voice.synthesize(sentence))
        self.player.wait()

    def respond(self, user_text: str) -> str:
        """Responde a una frase del visitante. Devuelve el texto final."""
        assert self.player is not None, "Llama a warmup() antes de hablar"

        # Identidad, historia y preguntas clave: respuesta canónica sin LLM.
        # Así siempre cuenta lo mismo, rápido y sin depender del modelo.
        canonical = persona.answer_identity(user_text)
        if canonical:
            started = time.perf_counter()
            splitter = SentenceStream()
            sentences = splitter.feed(canonical + " ") + splitter.flush()
            for sentence in sentences:
                self.player.play(self.voice.synthesize(sentence))
            self.player.flush()
            self.player.wait()
            self.last_latency = Latency(
                total_s=time.perf_counter() - started,
                chars=len(canonical),
            )
            return canonical

        started = time.perf_counter()
        splitter = SentenceStream()
        pieces: list[str] = []
        spoken: list[str] = []
        spoken_chars = 0
        cut = False
        latency = Latency()
        first_token_at: float | None = None
        first_audio_at: float | None = None

        def emit(sentence: str) -> None:
            nonlocal first_audio_at
            audio = self.voice.synthesize(sentence)
            if first_audio_at is None and audio.size:
                first_audio_at = time.perf_counter() - started
            self.player.play(audio)

        try:
            for chunk in self.brain.stream_reply(user_text):
                if first_token_at is None:
                    first_token_at = time.perf_counter() - started
                pieces.append(chunk)
                for sentence in splitter.feed(chunk):
                    emit(sentence)
                    spoken.append(sentence)
                    spoken_chars += len(sentence)
                    # Tope duro: cortamos por frase completa, nunca a mitad.
                    if config.MAX_REPLY_CHARS and spoken_chars >= config.MAX_REPLY_CHARS:
                        cut = True
                        break
                if cut:
                    break
        except BrainError as exc:
            console.print(f"[red]{exc}[/red]")
            reply = persona.fallback()
            emit(reply)
            self.player.wait()
            return reply

        if not cut:
            for sentence in splitter.flush():
                emit(sentence)
                spoken.append(sentence)

        # Vuelca el colchón del reproductor antes de esperar: si las frases
        # eran cortas, lo último sigue retenido y nunca sonaría.
        self.player.flush()
        self.player.wait()
        reply = " ".join(spoken).strip() or "".join(pieces).strip()

        latency.first_token_s = first_token_at or 0.0
        latency.first_audio_s = first_audio_at or 0.0
        latency.total_s = time.perf_counter() - started
        latency.chars = len(reply)
        self.last_latency = latency
        return reply

    # -- escucha ------------------------------------------------------------
    def listen(self) -> str | None:
        """Graba y transcribe. Devuelve None si no se detectó voz."""
        audio = self.mic.record()
        if audio is None or audio.size < config.MIC_SAMPLE_RATE * 0.2:
            return None
        started = time.perf_counter()
        text = self.transcriber.transcribe(audio)
        self.last_latency.stt_s = time.perf_counter() - started
        return text or None

    def turn(self) -> str | None:
        """Un turno completo: escuchar, responder y devolver lo dicho."""
        heard = self.listen()
        if heard is None:
            return None
        console.print(f"[cyan]Tú:[/cyan] {heard}")
        reply = self.respond(heard)
        if reply:
            console.print(f"[green]Springtrap:[/green] {reply}")
            console.print(f"[dim]{self.last_latency.summary()}[/dim]")
        return reply

    def roundtrip(self, text: str) -> str:
        """Prueba STT->TTS sin micrófono: sintetiza, transcribe y responde."""
        audio = self.voice.synthesize(text)
        started = time.perf_counter()
        heard = self.transcriber.transcribe(audio)
        self.last_latency.stt_s = time.perf_counter() - started
        console.print(f"[cyan]TTS->STT:[/cyan] {heard}")
        return self.respond(heard)


def silence(seconds: float) -> np.ndarray:
    return np.zeros(int(config.MIC_SAMPLE_RATE * seconds), dtype=np.float32)
