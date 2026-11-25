"""Buffer local JSONL resiliente ante caídas temporales de PostgreSQL."""

from __future__ import annotations

import json
from pathlib import Path
import threading
from typing import Any, Callable


class LocalTelemetryBuffer:
    """Almacena lecturas válidas en JSONL cuando PostgreSQL no responde y drena en lote."""

    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self._lock = threading.Lock()

    def append(self, record: dict[str, Any]) -> None:
        with self._lock:
            self.file_path.parent.mkdir(parents=True, exist_ok=True)
            with self.file_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
                fh.flush()

    def pending_count(self) -> int:
        with self._lock:
            if not self.file_path.exists():
                return 0
            with self.file_path.open("r", encoding="utf-8") as fh:
                return sum(1 for line in fh if line.strip())

    def drain(self, persist_fn: Callable[[dict[str, Any]], None]) -> int:
        """Drena en lote todos los registros pendientes hacia PostgreSQL.

        Si la base de datos falla a mitad del drenado, conserva los registros
        restantes sin pérdida de datos.
        """
        with self._lock:
            if not self.file_path.exists():
                return 0
            raw_lines = [ln for ln in self.file_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
            if not raw_lines:
                return 0

            restantes: list[str] = []
            drenados = 0
            for idx, line in enumerate(raw_lines):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    persist_fn(record)
                    drenados += 1
                except Exception:
                    restantes = raw_lines[idx:]
                    break

            if restantes:
                self.file_path.write_text("\n".join(restantes) + "\n", encoding="utf-8")
            else:
                self.file_path.unlink(missing_ok=True)
            return drenados
