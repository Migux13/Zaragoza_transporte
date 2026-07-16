import re
import requests
from homeassistant.components.sensor import SensorEntity
from .const import DOMAIN, API_URL, BUS_API_URL, BUS_AVANZA_URL

RE_MINUTOS = re.compile(r"(\d+)\s*min", re.IGNORECASE)


def parse_minutos(texto):
    """'12 minutos.' -> 12 | 'En la parada.' -> 0 | otro -> None."""
    if not texto:
        return None
    if "parada" in texto.lower():
        return 0
    match = RE_MINUTOS.search(texto)
    return int(match.group(1)) if match else None


RE_CELDAS = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
RE_FILAS = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
RE_TAGS = re.compile(r"<[^>]+>")


def _fetch_ayuntamiento(poste):
    """Destinos desde la API municipal, o None si falla o devuelve error."""
    try:
        response = requests.get(BUS_API_URL.format(poste=poste), timeout=15)
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None
    try:
        data = response.json()
    except ValueError:
        return None
    # el proxy devuelve a veces errores como JSON (p. ej. {"status": 400, ...})
    if "status" in data or "error" in data or "destinos" not in data:
        return None
    return data.get("destinos", [])


def _fetch_avanza(poste):
    """Destinos desde la web de tiempos de Avanza (HTML), o None si falla.

    Parsea la tabla LINEA/DESTINO/MIN. y agrupa por (linea, destino): la
    primera aparición es el primer bus y la segunda, el siguiente, imitando
    el formato de la API municipal.
    """
    try:
        response = requests.get(BUS_AVANZA_URL.format(poste=poste), timeout=15)
    except requests.RequestException:
        return None
    if response.status_code != 200:
        return None

    agrupado = {}
    orden = []
    for fila in RE_FILAS.findall(response.text):
        celdas = [RE_TAGS.sub("", c).strip() for c in RE_CELDAS.findall(fila)]
        if len(celdas) < 3:
            continue
        linea, destino, tiempo = celdas[0], celdas[1], celdas[2]
        if not linea or "linea" in linea.lower():
            continue  # cabecera
        if "parada" not in tiempo.lower() and not RE_MINUTOS.search(tiempo):
            continue  # fila sin tiempo válido (p. ej. la de accesibilidad)
        clave = (linea, destino)
        if clave not in agrupado:
            agrupado[clave] = {"linea": linea, "destino": destino,
                               "primero": tiempo, "segundo": None}
            orden.append(clave)
        elif agrupado[clave]["segundo"] is None:
            agrupado[clave]["segundo"] = tiempo
    if not orden:
        return None
    return [agrupado[k] for k in orden]


async def async_setup_entry(hass, entry, async_add_entities):
    tipo = entry.data.get("tipo", "tram")  # entradas antiguas no tienen "tipo"

    if tipo == "bus":
        poste = entry.data["poste"]
        nombre = entry.data.get("nombre")
        lat = entry.data.get("lat")
        lon = entry.data.get("lon")
        linea_filtro = entry.data.get("linea") or None

        if not linea_filtro and entry.data.get("modo") == "por_linea":
            # Una entidad por línea: un par próximo/siguiente por cada
            # línea descubierta del GTFS al configurar la parada.
            entities = []
            for linea in entry.data.get("lineas", []):
                entities.append(ZaragozaBusSensor(poste, linea, 1, nombre, lat, lon))
                entities.append(ZaragozaBusSensor(poste, linea, 2, nombre, lat, lon))
            async_add_entities(entities)
        else:
            # Sin línea concreta (modo combinado, por defecto), cada sensor
            # mezcla las llegadas de todas las líneas de la parada (línea
            # como atributo, ver ZaragozaBusSensor).
            async_add_entities([
                ZaragozaBusSensor(poste, linea_filtro, 1, nombre, lat, lon),
                ZaragozaBusSensor(poste, linea_filtro, 2, nombre, lat, lon),
            ])
    else:
        stop_id = entry.data.get("stop_id")
        stop_name = entry.data.get("stop_name")
        async_add_entities([
            ZaragozaTramSensor(stop_id, stop_name, 1),
            ZaragozaTramSensor(stop_id, stop_name, 2)
        ])


class ZaragozaTramSensor(SensorEntity):
    def __init__(self, stop_id, stop_name, tram_number):
        self._stop_id = stop_id
        self._stop_name = stop_name
        self._tram_number = tram_number
        self._state = None
        self._name = f"Tranvía {tram_number} - {stop_name}"
        self._attr_icon = "mdi:tram"
        self.entity_id = f"sensor.tranvia_{tram_number}_parada_{stop_id}"

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    def update(self):
        response = requests.get(API_URL)

        if response.status_code == 200:
            data = response.json()
            stops = data.get("result", [])

            # Find the stop with the given ID
            stop_data = next((stop for stop in stops if str(stop["id"]) == str(self._stop_id)), None)

            if stop_data:
                arrivals = stop_data.get("destinos", [])
                if arrivals:
                    self._state = arrivals[self._tram_number - 1].get("minutos")
                else:
                    self._state = "Sin datos"
            else:
                self._state = "Parada no encontrada"
        else:
            self._state = "Error al conectar"


class ZaragozaBusSensor(SensorEntity):
    """Bus N (1=próximo, 2=siguiente) en un poste, opcionalmente filtrado por línea.

    Sin filtro de línea, "próximo"/"siguiente" son las dos llegadas más
    cercanas de CUALQUIER línea que pase por la parada (no siempre coinciden
    con el "primero"/"segundo" de una única línea): la API devuelve las
    líneas en un orden que no está garantizado que sea por tiempo de llegada.
    """

    _attr_icon = "mdi:bus"
    _attr_native_unit_of_measurement = "min"

    # Separación (en grados) entre próximo y siguiente en el mapa: comparten
    # parada, así que sin esto sus marcadores caerían en el mismo punto y se
    # taparían entre sí. ~4-5 m, imperceptible a escala de calle.
    _OFFSET_MAPA = 0.00004

    def __init__(self, poste, linea, bus_number, nombre=None, lat=None, lon=None):
        self._poste = poste
        self._linea = linea
        self._bus_number = bus_number
        self._nombre = nombre
        if lat is not None and lon is not None:
            self._lat = lat + (self._OFFSET_MAPA if bus_number == 1 else -self._OFFSET_MAPA)
        else:
            self._lat = lat
        self._lon = lon
        self._state = None
        self._attrs = {}

        lugar = nombre or f"Parada {poste}"
        etiqueta = "próximo" if bus_number == 1 else "siguiente"
        etiqueta_id = "proximo" if bus_number == 1 else "siguiente"
        if linea:
            self._name = f"Bus {linea} {etiqueta} - {lugar}"
            self._attr_unique_id = f"{DOMAIN}_bus_{poste}_{linea}_{bus_number}"
            self.entity_id = f"sensor.bus_{linea.lower()}_{etiqueta_id}_parada_{poste}"
        else:
            self._name = f"Bus {etiqueta} - {lugar}"
            self._attr_unique_id = f"{DOMAIN}_bus_{poste}_{bus_number}"
            self.entity_id = f"sensor.bus_{etiqueta_id}_parada_{poste}"

    @property
    def name(self):
        return self._name

    @property
    def state(self):
        return self._state

    @property
    def extra_state_attributes(self):
        attrs = dict(self._attrs)
        attrs["numero_parada"] = self._poste
        if self._nombre:
            attrs.setdefault("parada", self._nombre)
        if self._lat is not None and self._lon is not None:
            # latitude/longitude hacen que HA muestre la parada en el mapa
            attrs["latitude"] = self._lat
            attrs["longitude"] = self._lon
        return attrs

    def update(self):
        fuente = "ayuntamiento"
        destinos = _fetch_ayuntamiento(self._poste)
        if destinos is None:
            # el proxy municipal falla o devolvió un error: probamos Avanza
            destinos = _fetch_avanza(self._poste)
            fuente = "avanza"
        if destinos is None:
            # ambas fuentes caídas: conservamos el último dato
            return

        if self._linea:
            destinos = [d for d in destinos if d.get("linea", "").upper() == self._linea.upper()]
            if not destinos:
                self._state = None
                self._attrs = {"fuente": fuente}
                return
            destino = destinos[0]
            campo = "primero" if self._bus_number == 1 else "segundo"
            self._set_estado(fuente, destino, campo)
            return

        # Sin filtro: mezclamos las llegadas (primero y segundo) de todas
        # las líneas de la parada y nos quedamos con la N-ésima más próxima.
        llegadas = []
        for destino in destinos:
            for campo in ("primero", "segundo"):
                minutos = parse_minutos(destino.get(campo))
                if minutos is not None:
                    llegadas.append((minutos, destino, campo))
        llegadas.sort(key=lambda item: item[0])

        if len(llegadas) < self._bus_number:
            self._state = None
            self._attrs = {"fuente": fuente}
            return

        _, destino, campo = llegadas[self._bus_number - 1]
        self._set_estado(fuente, destino, campo)

    def _set_estado(self, fuente, destino, campo):
        self._state = parse_minutos(destino.get(campo))
        self._attrs = {
            "fuente": fuente,
            "linea": destino.get("linea"),
            "destino": destino.get("destino"),
            "texto_original": destino.get(campo),
        }
