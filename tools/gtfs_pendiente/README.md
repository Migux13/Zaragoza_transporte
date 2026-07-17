Coloca aquí el ZIP del GTFS descargado a mano del NAP (ficha "Transporte
urbano de Zaragoza", requiere login — el login del NAP tiene reCAPTCHA, por
eso este paso no está automatizado) y haz push a `main`.

El workflow [`procesar-gtfs.yml`](../../.github/workflows/procesar-gtfs.yml)
detecta el `.zip`, regenera `postes_bus.json`, borra el `.zip` y abre una
Pull Request con el resultado para que la revises antes de mergear.
