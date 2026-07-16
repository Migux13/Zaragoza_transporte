"""Catálogo de postes de bus derivado del GTFS del NAP (transportes.gob.es).

Carga postes_bus.json (número de poste -> nombre, coordenadas, líneas) y
ofrece búsqueda por número, por nombre y por cercanía. El fichero se
regenera con tools/generar_postes.py cuando Avanza publica un GTFS nuevo.
"""

from __future__ import annotations

import json
import math
import os
import unicodedata

_RUTA_JSON = os.path.join(os.path.dirname(__file__), "postes_bus.json")
_catalogo: dict | None = None


def _cargar() -> dict:
    global _catalogo
    if _catalogo is None:
        with open(_RUTA_JSON, encoding="utf-8") as f:
            _catalogo = json.load(f)
    return _catalogo


def _normalizar(texto: str) -> str:
    """minúsculas y sin tildes, para búsqueda tolerante."""
    texto = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


def get_poste(numero: str) -> dict | None:
    """Datos de un poste por su número, o None si no está en el catálogo."""
    return _cargar()["postes"].get(str(int(numero)))


def buscar_por_nombre(consulta: str, limite: int = 15) -> list[tuple[str, dict]]:
    """Postes cuyo nombre contiene la consulta. [(numero, datos), ...]"""
    q = _normalizar(consulta)
    resultados = [
        (num, datos)
        for num, datos in _cargar()["postes"].items()
        if q in _normalizar(datos["nombre"])
    ]
    resultados.sort(key=lambda x: (len(x[1]["nombre"]), int(x[0])))
    return resultados[:limite]


def cercanos(lat: float, lon: float, limite: int = 10) -> list[tuple[str, dict, float]]:
    """Postes más cercanos a unas coordenadas. [(numero, datos, metros), ...]"""

    def haversine(lat2: float, lon2: float) -> float:
        r = 6371000.0
        p1, p2 = math.radians(lat), math.radians(lat2)
        dp = math.radians(lat2 - lat)
        dl = math.radians(lon2 - lon)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        return 2 * r * math.asin(math.sqrt(a))

    con_distancia = [
        (num, datos, haversine(datos["lat"], datos["lon"]))
        for num, datos in _cargar()["postes"].items()
    ]
    con_distancia.sort(key=lambda x: x[2])
    return con_distancia[:limite]
