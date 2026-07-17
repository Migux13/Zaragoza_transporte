# Mantenimiento (solo para el mantenedor)

## Regenerar el catálogo de paradas (postes_bus.json)

El GTFS caduca periódicamente (fecha en `valido_hasta` dentro de
`custom_components/zaragoza_transporte/postes_bus.json`). El workflow
[`.github/workflows/avisar-caducidad-gtfs.yml`](.github/workflows/avisar-caducidad-gtfs.yml)
comprueba esa fecha cada lunes y abre un *issue* de aviso si quedan ≤7 días
(sin duplicarlo mientras siga abierto).

### A mano

Descarga el ZIP actualizado del NAP (ficha "Transporte urbano de Zaragoza",
requiere cuenta gratuita) y ejecuta:

```bash
python3 tools/generar_postes.py fichero_gtfs.zip
```

y coloca el `postes_bus.json` resultante en `custom_components/zaragoza_transporte/`.

### Vía Pull Request automática

El login del NAP usa reCAPTCHA, así que la descarga no se puede automatizar
del todo. En su lugar:

1. Descarga a mano el ZIP del GTFS desde el NAP (cuenta gratuita).
2. Colócalo en `tools/gtfs_pendiente/` y haz push a `main`.
3. El workflow [`.github/workflows/procesar-gtfs.yml`](.github/workflows/procesar-gtfs.yml)
   detecta el `.zip`, regenera `postes_bus.json`, borra el `.zip` y abre una
   Pull Request con el resultado para revisarla antes de mergear (nunca hace
   push directo a `main`).

También se puede relanzar a mano desde la pestaña *Actions* → *Procesar GTFS
subido a mano* → *Run workflow*.
