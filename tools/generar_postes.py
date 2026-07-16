#!/usr/bin/env python3
"""Regenera postes_bus.json a partir del GTFS de Zaragoza del NAP.

Uso:
    python3 generar_postes.py <fichero_gtfs.zip>

Descarga el GTFS desde https://nap.transportes.gob.es (ficha "Transporte
urbano de Zaragoza", requiere cuenta gratuita) y pásale el zip.
Genera postes_bus.json con: numero de poste -> nombre, lat, lon, lineas.
"""
import csv
import io
import json
import re
import sys
import zipfile


def main(zip_path: str) -> None:
    with zipfile.ZipFile(zip_path) as z:
        def rows(name):
            with z.open(name) as f:
                yield from csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig"))

        trip2route = {r["trip_id"]: r["route_id"] for r in rows("trips.txt")}
        route_name = {r["route_id"]: r["route_short_name"] for r in rows("routes.txt")}

        stop_lineas: dict[str, set] = {}
        for r in rows("stop_times.txt"):
            linea = route_name[trip2route[r["trip_id"]]]
            stop_lineas.setdefault(r["stop_id"], set()).add(linea)

        feed = next(rows("feed_info.txt"))

        postes = {}
        for r in rows("stops.txt"):
            m = re.match(r"^PA0*(\d+)$", r.get("stop_code") or "")
            if not m:
                continue  # tranvía u otros códigos
            postes[m.group(1)] = {
                "nombre": r["stop_name"],
                "lat": round(float(r["stop_lat"]), 6),
                "lon": round(float(r["stop_lon"]), 6),
                "lineas": sorted(stop_lineas.get(r["stop_id"], set())),
            }

    out = {
        "fuente": "GTFS NAP transportes.gob.es - Transporte urbano de Zaragoza",
        "version_feed": feed.get("feed_version", ""),
        "valido_hasta": feed.get("feed_end_date", ""),
        "postes": postes,
    }
    with open("postes_bus.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"postes_bus.json generado: {len(postes)} postes "
          f"(feed {out['version_feed']}, válido hasta {out['valido_hasta']})")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
