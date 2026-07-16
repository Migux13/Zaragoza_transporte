from homeassistant import config_entries
import voluptuous as vol
from .const import DOMAIN, PARADAS
from . import gtfs


class ZaragozaTransporteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._candidatos: dict[str, str] = {}  # etiqueta -> numero de poste
        self._poste: str | None = None

    # ------------------------------------------------------------------ raíz
    async def async_step_user(self, user_input=None):
        """Primer paso: elegir tranvía o bus."""
        if user_input is not None:
            if user_input["tipo"] == "Tranvía":
                return await self.async_step_tram()
            return await self.async_step_bus()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("tipo", default="Tranvía"): vol.In(["Tranvía", "Bus"]),
            }),
        )

    # --------------------------------------------------------------- tranvía
    async def async_step_tram(self, user_input=None):
        """Configuración de parada de tranvía (comportamiento original)."""
        if user_input is not None:
            stop_name = user_input["stop_name"]
            stop_id = next(id for id, name in PARADAS if name == stop_name)
            return self.async_create_entry(
                title=f"Parada {stop_name}",
                data={"tipo": "tram", "stop_id": stop_id, "stop_name": stop_name},
            )

        nombres_paradas = list({name for _, name in PARADAS})
        return self.async_show_form(
            step_id="tram",
            data_schema=vol.Schema({
                vol.Required("stop_name"): vol.In(nombres_paradas),
            }),
        )

    # ------------------------------------------------------------------- bus
    async def async_step_bus(self, user_input=None):
        """Elegir cómo localizar el poste de bus."""
        if user_input is not None:
            modo = user_input["modo"]
            if modo == "Por número de poste":
                return await self.async_step_bus_numero()
            if modo == "Por nombre de parada":
                return await self.async_step_bus_nombre()
            return await self.async_step_bus_cerca()

        return self.async_show_form(
            step_id="bus",
            data_schema=vol.Schema({
                vol.Required("modo", default="Por número de poste"): vol.In([
                    "Por número de poste",
                    "Por nombre de parada",
                    "Paradas cercanas",
                ]),
            }),
        )

    async def async_step_bus_numero(self, user_input=None):
        """Poste por número de marquesina, validado contra el catálogo GTFS."""
        errors = {}
        if user_input is not None:
            poste = user_input["poste"].strip()
            datos = None
            if poste.isdigit():
                datos = await self.hass.async_add_executor_job(gtfs.get_poste, poste)
            if datos is None:
                errors["base"] = "invalid_poste"
            else:
                self._poste = str(int(poste))
                return await self.async_step_bus_linea()

        return self.async_show_form(
            step_id="bus_numero",
            data_schema=vol.Schema({vol.Required("poste"): str}),
            errors=errors,
        )

    async def async_step_bus_nombre(self, user_input=None):
        """Buscar parada por nombre (búsqueda parcial, sin tildes)."""
        errors = {}
        if user_input is not None:
            resultados = await self.hass.async_add_executor_job(
                gtfs.buscar_por_nombre, user_input["nombre"]
            )
            if not resultados:
                errors["base"] = "no_results"
            else:
                self._candidatos = {
                    f"({num}) {d['nombre']} — líneas {', '.join(d['lineas'])}": num
                    for num, d in resultados
                }
                return await self.async_step_bus_elegir()

        return self.async_show_form(
            step_id="bus_nombre",
            data_schema=vol.Schema({vol.Required("nombre"): str}),
            errors=errors,
        )

    async def async_step_bus_cerca(self, user_input=None):
        """Paradas más cercanas a la ubicación configurada en Home Assistant."""
        lat = self.hass.config.latitude
        lon = self.hass.config.longitude
        resultados = await self.hass.async_add_executor_job(gtfs.cercanos, lat, lon)
        self._candidatos = {
            f"({num}) {d['nombre']} — {int(m)} m — líneas {', '.join(d['lineas'])}": num
            for num, d, m in resultados
        }
        return await self.async_step_bus_elegir()

    async def async_step_bus_elegir(self, user_input=None):
        """Elegir un poste de la lista de candidatos."""
        if user_input is not None:
            self._poste = self._candidatos[user_input["parada"]]
            return await self.async_step_bus_linea()

        return self.async_show_form(
            step_id="bus_elegir",
            data_schema=vol.Schema({
                vol.Required("parada"): vol.In(list(self._candidatos)),
            }),
        )

    async def async_step_bus_linea(self, user_input=None):
        """Elegir línea concreta o todas las del poste, y crear la entrada."""
        datos = await self.hass.async_add_executor_job(gtfs.get_poste, self._poste)
        opciones = ["Todas"] + datos["lineas"]

        if user_input is not None:
            linea = user_input["linea"]
            linea = "" if linea == "Todas" else linea

            unique_id = f"bus_{self._poste}_{linea}" if linea else f"bus_{self._poste}"
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured()

            title = f"Bus {datos['nombre']} ({self._poste})"
            if linea:
                title += f" línea {linea}"
            return self.async_create_entry(
                title=title,
                data={
                    "tipo": "bus",
                    "poste": self._poste,
                    "linea": linea,
                    "nombre": datos["nombre"],
                    "lat": datos["lat"],
                    "lon": datos["lon"],
                    "lineas": datos["lineas"],
                },
            )

        return self.async_show_form(
            step_id="bus_linea",
            data_schema=vol.Schema({
                vol.Required("linea", default="Todas"): vol.In(opciones),
            }),
        )
