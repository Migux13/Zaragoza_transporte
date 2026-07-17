#!/usr/bin/env python3
"""Comprueba si el GTFS de postes_bus.json caduca pronto y, si es así,
descarga el GTFS actualizado del NAP (requiere cuenta gratuita) y regenera
postes_bus.json.

Variables de entorno requeridas:
    NAP_EMAIL, NAP_PASSWORD  -- credenciales de una cuenta del NAP

Uso:
    python3 actualizar_gtfs.py [--dias-margen N] [--forzar]

Sin --forzar, no hace nada (sale con código 0) si aún faltan más de N días
(por defecto 7) para la caducidad. Sale con código distinto de 0 si algo
falla (login, descarga, parseo), para que el workflow de CI lo detecte.
"""
import argparse
import datetime
import json
import os
import re
import sys
import tempfile

import requests

sys.path.insert(0, os.path.dirname(__file__))
import generar_postes  # noqa: E402

NAP_BASE = "https://nap.transportes.gob.es"
NAP_LOGIN_URL = f"{NAP_BASE}/Account/Login"
NAP_LOGIN_POST_URL = f"{NAP_BASE}/Account/LogIn"
NAP_DATASET_URL = f"{NAP_BASE}/Files/Detail/975"  # ficha "Transporte urbano de Zaragoza"

POSTES_JSON = os.path.join(
    os.path.dirname(__file__), "..", "custom_components", "zaragoza_transporte", "postes_bus.json"
)

RE_TOKEN = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"')
RE_ENLACES = re.compile(r'<a\s[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
RE_DESCARGA_TEXTO = re.compile(r"Descargar\s*\([\d.,]+\s*MB\)", re.IGNORECASE)


def dias_para_caducar() -> int:
    """Días hasta que caduque el catálogo actual. 0 si no existe o no se puede leer."""
    if not os.path.exists(POSTES_JSON):
        return 0
    with open(POSTES_JSON, encoding="utf-8") as f:
        actual = json.load(f)
    valido_hasta = actual.get("valido_hasta", "")
    if not valido_hasta:
        return 0
    fecha = datetime.datetime.strptime(valido_hasta, "%Y%m%d").date()
    return (fecha - datetime.date.today()).days


def login(session: requests.Session) -> None:
    for var in ("NAP_EMAIL", "NAP_PASSWORD"):
        if not os.environ.get(var):
            raise RuntimeError(f"Falta la variable de entorno {var}")

    resp = session.get(NAP_LOGIN_URL, timeout=30)
    resp.raise_for_status()
    m = RE_TOKEN.search(resp.text)
    if not m:
        raise RuntimeError("No se encontró __RequestVerificationToken en la página de login del NAP")
    token = m.group(1)

    resp = session.post(
        NAP_LOGIN_POST_URL,
        data={
            "ReturnUrl": "",
            "Email": os.environ["NAP_EMAIL"],
            "Password": os.environ["NAP_PASSWORD"],
            "Remember": "false",
            "__RequestVerificationToken": token,
        },
        timeout=30,
    )
    resp.raise_for_status()
    print(f"[debug] tras POST login: status={resp.status_code} url_final={resp.url}")
    if re.search(r"field-validation-error|text-danger|ValidationSummary|credenciales", resp.text, re.IGNORECASE):
        m = re.search(
            r'(?:field-validation-error|text-danger|ValidationSummary)[^>]*>([^<]{1,200})', resp.text, re.IGNORECASE
        )
        print(f"[debug] posible mensaje de error de login: {m.group(1).strip() if m else '(no extraído)'}")


def extraer_enlace_descarga(html: str) -> str:
    for href, contenido in RE_ENLACES.findall(html):
        if RE_DESCARGA_TEXTO.search(contenido):
            return href
    # Diagnóstico: ¿aparece "escargar" en algún sitio y con qué pinta?
    for m in re.finditer(r".{80}[Dd]escargar.{80}", html, re.DOTALL):
        print(f"[debug] contexto alrededor de 'escargar': {m.group(0)!r}")
    raise RuntimeError(
        "No se encontró el enlace de descarga en la ficha del dataset del NAP "
        "(puede que la página haya cambiado, o que el login haya fallado)"
    )


def descargar_zip(session: requests.Session) -> bytes:
    resp = session.get(NAP_DATASET_URL, timeout=30)
    resp.raise_for_status()
    print(f"[debug] ficha dataset: status={resp.status_code} url_final={resp.url} tamaño={len(resp.text)}")
    href = extraer_enlace_descarga(resp.text)

    if "/Account/Login" in href:
        raise RuntimeError("Login en el NAP fallido: la sesión sigue sin autenticar (revisa NAP_EMAIL/NAP_PASSWORD)")

    url_descarga = href if href.startswith("http") else NAP_BASE + href
    resp = session.get(url_descarga, timeout=120)
    resp.raise_for_status()
    if resp.content[:2] != b"PK":
        raise RuntimeError("La descarga no parece un ZIP válido (cabecera inesperada)")
    return resp.content


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dias-margen", type=int, default=7)
    parser.add_argument("--forzar", action="store_true")
    args = parser.parse_args()

    restantes = dias_para_caducar()
    if restantes > args.dias_margen and not args.forzar:
        print(f"El catálogo actual es válido {restantes} días más (margen {args.dias_margen}): nada que hacer.")
        return 0

    print(f"Actualizando catálogo (quedan {restantes} días, margen {args.dias_margen} días, forzar={args.forzar})...")

    session = requests.Session()
    session.headers["User-Agent"] = (
        "zaragoza-transporte-bot/1.0 (+https://github.com/Migux13/Zaragoza_transporte)"
    )
    login(session)
    zip_bytes = descargar_zip(session)

    with tempfile.NamedTemporaryFile(suffix=".zip") as tmp:
        tmp.write(zip_bytes)
        tmp.flush()
        generar_postes.main(tmp.name, out_path=POSTES_JSON)

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001 - queremos que cualquier fallo salga con código != 0
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
