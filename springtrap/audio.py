"""Micrófono con VAD por energía y reproductor con colchón.

El reproductor es un colchón + cola + hilo: mientras suena una frase, el LLM y
Piper siguen trabajando en la siguiente. El colchón evita el fallo más visible
del streaming: si la primera frase dura menos que lo que tarda en llegar la
segunda, el dispositivo se queda sin datos y se oye un silencio. Acumulando
``cushion_s`` antes de empezar, la segunda frase ya está lista cuando termina la
primera. Además expone ``on_level`` (RMS por bloque de 50 ms), que es lo que
necesitará el servo de la mandíbula.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from collections import deque
from collections.abc import Callable

import numpy as np
import sounddevice as sd

from . import config

LevelCallback = Callable[[float], None]

# Envoltorios y dispositivos virtuales de Windows: se anuncian como micrófonos
# pero meten latencia (MME) o capturan lo que suena por el altavoz.
_VIRTUAL_INPUT_HINTS = (
    "asignador de sonido",
    "sound mapper",
    "controlador primario",
    "primary sound",
    "mezcla estéreo",
    "stereo mix",
    "nahimic",
    "monitor",
    "what u hear",
    "loopback",
)

_PREFERRED_INPUT_HINTS = (
    "varios micrófonos",
    "micrófonos",
    "mic array",
    "array",
    "micrófono",
    "microphone",
)


def hostapi_name(device: int | str | None) -> str:
    """Nombre del host API del dispositivo (WASAPI, MME, ALSA, PulseAudio...)."""
    try:
        index = sd.query_devices(device, "input")["hostapi"]
        return str(sd.query_hostapis(index)["name"])
    except Exception:
        return ""


def pick_input_device(preferred: str | int | None = None) -> int | None:
    """Índice del micrófono más razonable, evitando los envoltorios de Windows.

    ``preferred`` acepta un índice (``"9"``) o un trozo del nombre
    (``"realtek hd audio mic"``). Si no se encuentra, se ignora y se elige solo.
    """
    devices = list(enumerate(sd.query_devices()))
    inputs = [(i, d) for i, d in devices if d["max_input_channels"] > 0]
    if not inputs:
        return None

    if preferred not in (None, ""):
        text = str(preferred).strip()
        if text.isdigit():
            index = int(text)
            if any(i == index for i, _ in inputs):
                return index
        needle = text.lower()
        for index, device in inputs:
            if needle in device["name"].lower():
                return index

    def score(item: tuple[int, dict]) -> int:
        index, device = item
        name = device["name"].lower()
        points = 0
        if any(bad in name for bad in _VIRTUAL_INPUT_HINTS):
            points -= 100
        # WASAPI es el que menos latencia añade y el único con auto_convert.
        if "wasapi" in hostapi_name(index).lower():
            points += 40
        if any(good in name for good in _PREFERRED_INPUT_HINTS):
            points += 10
        if "realtek" in name:
            points += 5
        points += min(int(device["max_input_channels"]), 4)
        return points

    best = max(inputs, key=score)
    return best[0] if score(best) > 0 else None


def resample_audio(audio: np.ndarray, src_rate: int, dst_rate: int) -> np.ndarray:
    """Remuestrea voz mono. Usa PyAV (viene con faster-whisper) y cae a numpy."""
    if not audio.size or src_rate == dst_rate:
        return audio

    try:
        import av

        frame = av.AudioFrame.from_ndarray(
            audio.reshape(1, -1).astype(np.float32), format="flt", layout="mono"
        )
        frame.sample_rate = src_rate
        resampler = av.AudioResampler(format="flt", layout="mono", rate=dst_rate)
        pieces = [chunk.to_ndarray().reshape(-1) for chunk in resampler.resample(frame)]
        pieces.extend(chunk.to_ndarray().reshape(-1) for chunk in resampler.resample(None))
        if pieces:
            return np.concatenate(pieces).astype(np.float32)
    except Exception:
        pass

    # Último recurso: interpolación lineal. Para voz a 16 kHz es suficiente.
    out_len = int(round(len(audio) * dst_rate / src_rate))
    if out_len <= 0:
        return np.zeros(0, dtype=np.float32)
    return np.interp(
        np.linspace(0, len(audio) - 1, out_len, dtype=np.float64),
        np.arange(len(audio), dtype=np.float64),
        audio,
    ).astype(np.float32)


class Mic:
    """Graba una intervención completa hasta detectar silencio.

    Elige solo un micrófono real (evita el «Asignador de sonido» de Windows),
    pide 16 kHz con conversión automática en WASAPI y, si el dispositivo no lo
    acepta, graba a su frecuencia nativa y remuestrea.
    """

    def __init__(
        self,
        samplerate: int = config.MIC_SAMPLE_RATE,
        device: str | None = config.MIC_DEVICE,
    ) -> None:
        self.samplerate = samplerate
        self.device = device
        self.last_device: int | None = None

    @property
    def resolved(self) -> int | None:
        return pick_input_device(self.device)

    def describe(self) -> str:
        try:
            index = self.resolved
            if index is None:
                return "dispositivo por defecto"
            info = sd.query_devices(index)
            return f"[{index}] {info['name']} · {hostapi_name(index)}"
        except Exception as error:  # nunca debe tumbar el arranque
            return f"no disponible ({error})"

    def check(self) -> dict:
        index = self.resolved
        info = sd.query_devices(index, "input")
        return {
            "name": info["name"],
            "channels": info["max_input_channels"],
            "samplerate": info["default_samplerate"],
            "hostapi": hostapi_name(index),
        }

    def _extra_settings(self, device: int | None):
        """WASAPI: deja que Windows convierta a 16 kHz por nosotros."""
        if os.name != "nt" or "wasapi" not in hostapi_name(device).lower():
            return None
        try:
            return sd.WasapiSettings(auto_convert=True)
        except Exception:
            return None

    def _capture(
        self,
        device: int | None,
        samplerate: int,
        extra_settings,
        silence_s: float,
        max_s: float,
        start_timeout_s: float,
    ) -> np.ndarray | None:
        block = int(samplerate * 0.03)
        frames: queue.Queue[np.ndarray] = queue.Queue()

        def callback(indata, _frames, _time, _status):
            frames.put(indata[:, 0].copy())

        pre_roll: deque[np.ndarray] = deque(maxlen=10)  # ~300 ms antes de hablar
        collected: list[np.ndarray] = []
        speaking = False
        silence_start: float | None = None
        noise_floor: float | None = None

        started = time.perf_counter()
        with sd.InputStream(
            samplerate=samplerate,
            channels=1,
            dtype="float32",
            callback=callback,
            blocksize=block,
            device=device,
            extra_settings=extra_settings,
        ):
            while True:
                elapsed = time.perf_counter() - started
                if not speaking and elapsed > start_timeout_s:
                    return None
                if elapsed > max_s:
                    break

                try:
                    frame = frames.get(timeout=0.25)
                except queue.Empty:
                    continue

                rms = float(np.sqrt(np.mean(frame * frame)) + 1e-9)

                if noise_floor is None:
                    noise_floor = rms
                elif not speaking:
                    noise_floor = 0.98 * noise_floor + 0.02 * rms

                threshold = min(
                    config.VAD_THRESHOLD_MAX,
                    max(config.VAD_THRESHOLD_MIN, (noise_floor or 0.0) * config.VAD_NOISE_MULT),
                )

                if not speaking:
                    if rms > threshold:
                        speaking = True
                        collected.extend(pre_roll)
                        collected.append(frame)
                        silence_start = None
                    else:
                        pre_roll.append(frame)
                    continue

                collected.append(frame)
                if rms < threshold * 0.8:
                    silence_start = silence_start or elapsed
                    if elapsed - silence_start >= silence_s:
                        break
                else:
                    silence_start = None

        if not collected:
            return None
        return np.concatenate(collected).astype(np.float32)

    def record(
        self,
        silence_s: float = config.VAD_SILENCE_S,
        max_s: float = config.VAD_MAX_UTTERANCE_S,
        start_timeout_s: float = config.VAD_START_TIMEOUT_S,
    ) -> np.ndarray | None:
        """Graba hasta ``silence_s`` de silencio. Devuelve None si nadie habló."""
        device = self.resolved
        self.last_device = device

        try:
            return self._capture(
                device,
                self.samplerate,
                self._extra_settings(device),
                silence_s,
                max_s,
                start_timeout_s,
            )
        except sd.PortAudioError:
            # El dispositivo no acepta 16 kHz: grabamos a su frecuencia nativa.
            native = int(round(sd.query_devices(device, "input")["default_samplerate"]))
            if native == self.samplerate:
                raise
            audio = self._capture(
                device, native, None, silence_s, max_s, start_timeout_s
            )
            if audio is None:
                return None
            return resample_audio(audio, native, self.samplerate)

    def _raw(self, device, samplerate: int, extra_settings, seconds: float) -> np.ndarray:
        frames = max(1, int(samplerate * seconds))
        with sd.InputStream(
            samplerate=samplerate,
            channels=1,
            dtype="float32",
            device=device,
            blocksize=max(1, int(samplerate * 0.03)),
            extra_settings=extra_settings,
        ) as stream:
            data, _overflowed = stream.read(frames)
        return data[:, 0].copy()

    def probe(self, seconds: float = 1.5) -> np.ndarray:
        """Captura cruda (sin VAD) para medir el nivel real de entrada.

        Es lo que distingue «no has hablado» de «Windows está entregando
        silencio absoluto», que en un portátil suele ser la tecla de silencio
        del micro o un endpoint deshabilitado.
        """
        device = self.resolved
        self.last_device = device
        try:
            return self._raw(
                device, self.samplerate, self._extra_settings(device), seconds
            )
        except sd.PortAudioError:
            native = int(round(sd.query_devices(device, "input")["default_samplerate"]))
            if native == self.samplerate:
                raise
            return resample_audio(
                self._raw(device, native, None, seconds), native, self.samplerate
            )


class Player:
    """Colchón + cola de reproducción con callback de nivel para la mandíbula.

    ``play()`` no empieza a sonar hasta acumular ``cushion_s`` de audio. Así la
    frase siguiente ya está sintetizada cuando se acaba la actual y no hay
    silencios entre frases. Al final del turno hay que llamar a ``flush()`` (o a
    ``wait()``, que lo hace solo) para vaciar lo que quede en el colchón.
    """

    def __init__(
        self,
        samplerate: int,
        device: str | None = config.OUTPUT_DEVICE,
        on_level: LevelCallback | None = None,
        cushion_s: float = 0.5,
    ) -> None:
        self.samplerate = samplerate
        self.device = device
        self.on_level = on_level
        self.cushion_s = cushion_s
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._pending = 0
        self._condition = threading.Condition()
        self._staging: list[np.ndarray] = []
        self._staged = 0
        self._stage_lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="player")
        self._thread.start()

    def play(self, audio: np.ndarray) -> None:
        if not audio.size:
            return
        with self._stage_lock:
            self._staging.append(audio)
            self._staged += audio.size
            if self._staged < self.cushion_s * self.samplerate:
                return
            audio = np.concatenate(self._staging)
            self._staging.clear()
            self._staged = 0
        self._enqueue(audio)

    def flush(self) -> None:
        """Vuelca el colchón a la cola. Fin de turno o audio más corto que él."""
        with self._stage_lock:
            if not self._staging:
                return
            audio = np.concatenate(self._staging)
            self._staging.clear()
            self._staged = 0
        self._enqueue(audio)

    def _enqueue(self, audio: np.ndarray) -> None:
        with self._condition:
            self._pending += 1
        self._queue.put(audio)

    def _run(self) -> None:
        # 50 ms por bloque: absorben los tirones del GIL mientras Piper sintetiza
        # la frase siguiente. Con 20 ms el reproductor iba demasiado justo.
        block = max(256, int(self.samplerate * 0.05))
        # blocksize fijo: PortAudio exige bloques exactos, así que rellenamos
        # el último con ceros. Escribir un bloque corto corrompe memoria.
        with sd.OutputStream(
            samplerate=self.samplerate,
            channels=1,
            dtype="float32",
            blocksize=block,
            device=self.device,
        ) as stream:
            while not self._stop.is_set():
                try:
                    audio = self._queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                if audio is None:
                    break

                for start in range(0, len(audio), block):
                    chunk = audio[start : start + block]
                    if len(chunk) < block:
                        chunk = np.pad(chunk, (0, block - len(chunk)))
                    stream.write(chunk)
                    if self.on_level is not None:
                        self.on_level(float(np.sqrt(np.mean(chunk * chunk))))

                if self.on_level is not None:
                    self.on_level(0.0)

                with self._condition:
                    self._pending -= 1
                    if self._pending <= 0:
                        self._pending = 0
                        self._condition.notify_all()

    def wait(self) -> None:
        """Espera a que termine de sonar todo. Vuelca antes el colchón."""
        self.flush()
        with self._condition:
            while self._pending > 0 and not self._stop.is_set():
                self._condition.wait(timeout=0.5)

    def stop(self) -> None:
        """Corta la reproducción (barge-in)."""
        with self._stage_lock:
            self._staging.clear()
            self._staged = 0
        try:
            while True:
                self._queue.get_nowait()
        except queue.Empty:
            pass
        with self._condition:
            self._pending = 0
            self._condition.notify_all()

    def close(self) -> None:
        self.wait()
        self._stop.set()
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=3)
