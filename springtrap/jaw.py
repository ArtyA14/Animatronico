"""Mandíbula: convierte el nivel de voz (RMS) en un ángulo para el ESP32.

El ``Player`` entrega el RMS de cada bloque de 50 ms. Esta clase lo pasa a
dBFS, lo normaliza entre un piso y un techo, lo suaviza y envía el ángulo por
el puerto serie. El ESP32 solo obedece: aquí está toda la calibración.

Cadena completa::

    voz -> Player.on_level(rms) -> Jaw.update() -> "37\\n" -> ESP32 -> SG90

El RMS de un bloque de 50 ms es suficiente para una mandíbula: a 20 Hz se
puede seguir el ritmo de las sílabas sin que el servo parezca nervioso.
"""

from __future__ import annotations

import math
import time

from . import config


class Jaw:
    """Controla la mandíbula por USB serie.

    Si el puerto no se abre, lanza la excepción de ``pyserial``; el pipeline la
    captura y sigue funcionando sin mandíbula.
    """

    def __init__(
        self,
        port: str = config.JAW_PORT,
        baudrate: int = config.JAW_BAUDRATE,
        min_angle: int = config.JAW_MIN_ANGLE,
        max_angle: int = config.JAW_MAX_ANGLE,
        floor_db: float = config.JAW_FLOOR_DB,
        ceil_db: float = config.JAW_CEIL_DB,
        gamma: float = config.JAW_GAMMA,
        attack: float = config.JAW_ATTACK,
        release: float = config.JAW_RELEASE,
        slew_deg_s: float = config.JAW_SLEW,
        deadband: float = config.JAW_DEADBAND,
        heartbeat_s: float = config.JAW_HEARTBEAT_S,
    ) -> None:
        import serial  # import perezoso: el resto del proyecto no depende de pyserial

        if max_angle <= min_angle:
            raise ValueError(f"JAW_MAX_ANGLE ({max_angle}) debe ser mayor que JAW_MIN_ANGLE ({min_angle})")
        if ceil_db <= floor_db:
            raise ValueError(f"JAW_CEIL_DB ({ceil_db}) debe ser mayor que JAW_FLOOR_DB ({floor_db})")

        self.min_angle = float(min_angle)
        self.max_angle = float(max_angle)
        self.floor_db = float(floor_db)
        self.ceil_db = float(ceil_db)
        self.gamma = float(gamma)
        self.attack = float(attack)
        self.release = float(release)
        self.slew_deg_s = float(slew_deg_s)
        self.deadband = float(deadband)
        self.heartbeat_s = float(heartbeat_s)

        self._serial = serial.Serial(
            port=port,
            baudrate=baudrate,
            timeout=0,
            write_timeout=0.05,
        )
        # Abrir el puerto resetea el ESP32 (DTR). Le damos un momento para que
        # arranque antes del primer comando; el heartbeat recupera lo perdido.
        time.sleep(0.4)

        self._angle = self.min_angle
        self._last_sent = None
        self._last_sent_at = 0.0
        self._last_update_at = time.perf_counter()
        self._send(self.min_angle)

    # -- conversión ---------------------------------------------------------
    @property
    def angle(self) -> float:
        """Último ángulo suavizado (grados)."""
        return self._angle

    def move_to(self, angle: float) -> None:
        """Mueve a un ángulo concreto (para barridos y pruebas manuales)."""
        value = min(self.max_angle, max(self.min_angle, float(angle)))
        self._angle = value
        self._send(value)

    def target_angle(self, rms: float) -> float:
        """RMS lineal (0..1) -> ángulo objetivo, sin suavizado."""
        if rms <= 0.0:
            return self.min_angle

        db = 20.0 * math.log10(max(rms, 1e-6))
        norm = (db - self.floor_db) / (self.ceil_db - self.floor_db)
        norm = min(1.0, max(0.0, norm))
        shaped = norm**self.gamma
        return self.min_angle + (self.max_angle - self.min_angle) * shaped

    # -- bucle principal ----------------------------------------------------
    def update(self, rms: float) -> None:
        """Avanza un paso con el RMS actual. Lo llama el hilo del ``Player``."""
        now = time.perf_counter()

        target = self.target_angle(rms)
        previous = self._angle
        # Ataque rápido al abrir, liberación lenta al cerrar: sigue las
        # sílabas sin castañetear entre ellas.
        alpha = self.attack if target > previous else self.release
        smoothed = previous + alpha * (target - previous)

        # Límite de velocidad: el SG90 no puede saltar 50° en un bloque.
        dt = now - self._last_update_at
        self._last_update_at = now
        max_step = self.slew_deg_s * max(dt, 1e-3)
        if smoothed > previous + max_step:
            smoothed = previous + max_step
        elif smoothed < previous - max_step:
            smoothed = previous - max_step

        self._angle = min(self.max_angle, max(self.min_angle, smoothed))

        # Zona muerta + heartbeat: no mandamos ruido por cada grado, pero si
        # pasan heartbeat_s sin hablar el ESP32 no debe cerrar por watchdog.
        changed = self._last_sent is None or abs(self._angle - self._last_sent) >= self.deadband
        stale = now - self._last_sent_at >= self.heartbeat_s
        if changed or stale:
            self._send(self._angle)

    # -- serie --------------------------------------------------------------
    def _send(self, angle: float) -> None:
        value = int(round(angle))
        try:
            self._serial.write(f"{value}\n".encode("ascii"))
        except Exception:
            # Un fallo puntual (ESP32 desconectado) no debe tumbar la voz.
            # El siguiente update lo reintenta.
            return

        self._angle = float(angle)
        self._last_sent = float(angle)
        self._last_sent_at = time.perf_counter()

    def close(self) -> None:
        """Cierra la boca y libera el puerto."""
        try:
            self._send(self.min_angle)
            time.sleep(0.15)  # deja salir el último comando
        finally:
            try:
                self._serial.close()
            except Exception:
                pass
