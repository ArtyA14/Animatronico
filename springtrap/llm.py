"""Cliente de Ollama con streaming y memoria de conversación."""

from __future__ import annotations

import json
from collections.abc import Iterator

import requests

from . import config, persona


class BrainError(RuntimeError):
    """Fallo al hablar con Ollama (servicio caído, modelo ausente, etc.)."""


class Brain:
    def __init__(
        self,
        model: str = config.LLM_MODEL,
        url: str = config.OLLAMA_URL,
        num_ctx: int = config.LLM_NUM_CTX,
        max_tokens: int = config.LLM_MAX_TOKENS,
        temperature: float = config.LLM_TEMPERATURE,
        history_turns: int = config.LLM_HISTORY_TURNS,
    ) -> None:
        self.model = model
        self.url = url.rstrip("/")
        self.num_ctx = num_ctx
        self.max_tokens = max_tokens
        self.temperature = temperature
        self.history_turns = history_turns
        self._history: list[dict[str, str]] = []

    # -- estado -------------------------------------------------------------
    def reset(self) -> None:
        self._history.clear()

    @property
    def history(self) -> list[dict[str, str]]:
        return list(self._history)

    def _trim(self) -> None:
        limit = max(1, self.history_turns) * 2
        if len(self._history) > limit:
            self._history = self._history[-limit:]

    # -- arranque -----------------------------------------------------------
    def warmup(self) -> float:
        """Carga el modelo en VRAM para que el primer turno no tarde 10 s.

        Devuelve los segundos que ha tardado.
        """
        import time

        started = time.perf_counter()
        payload = {
            "model": self.model,
            "prompt": "",
            "stream": False,
            "keep_alive": config.LLM_KEEP_ALIVE,
            "options": {"num_predict": 1, "num_ctx": self.num_ctx},
        }
        try:
            response = requests.post(f"{self.url}/api/generate", json=payload, timeout=180)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise BrainError(
                f"No puedo hablar con Ollama en {self.url}. "
                "¿Está arrancado 'ollama serve' y descargado el modelo?"
            ) from exc
        return time.perf_counter() - started

    # -- conversación -------------------------------------------------------
    def stream_reply(self, user_text: str) -> Iterator[str]:
        """Genera la respuesta por trozos, manteniendo el historial."""
        user_text = user_text.strip()
        if not user_text:
            return

        self._history.append({"role": "user", "content": user_text})

        messages = [{"role": "system", "content": persona.SYSTEM_PROMPT}, *self._history]
        payload = {
            "model": self.model,
            "messages": messages,
            "stream": True,
            "keep_alive": config.LLM_KEEP_ALIVE,
            "options": {
                "temperature": self.temperature,
                "top_p": config.LLM_TOP_P,
                "repeat_penalty": 1.1,
                "num_ctx": self.num_ctx,
                "num_predict": self.max_tokens,
                "stop": ["\nUsuario:", "\nUser:", "\n\n"],
            },
        }

        parts: list[str] = []
        try:
            with requests.post(
                f"{self.url}/api/chat", json=payload, stream=True, timeout=(5, 120)
            ) as response:
                if response.status_code == 404:
                    raise BrainError(
                        f"El modelo '{self.model}' no está descargado. "
                        f"Ejecuta: ollama pull {self.model}"
                    )
                response.raise_for_status()

                for line in response.iter_lines():
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    if error := event.get("error"):
                        raise BrainError(str(error))

                    chunk = event.get("message", {}).get("content", "")
                    if chunk:
                        parts.append(chunk)
                        yield chunk

                    if event.get("done"):
                        break
        finally:
            reply = "".join(parts).strip()
            if reply:
                self._history.append({"role": "assistant", "content": reply})
                self._trim()
            else:
                # Sin respuesta válida: no ensuciamos el historial.
                self._history.pop()
