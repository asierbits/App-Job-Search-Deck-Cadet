"""Búsqueda de empresas y agencias.

Fuentes:
  - maritimo: navieras europeas de Wikidata y de directorios de asociaciones de navieros (maritimo.py)
  - ejemplo: empresas ficticias con correos @example.* (dominios reservados, nunca llegan a nadie)
  - osm:     OpenStreetMap (gratis y sin clave). Busca agencias de empleo y oficinas de empresas
             alrededor de cada ciudad de la lista, en cualquier país. Solo se quedan las que publican
             email o web (sin ninguno de los dos no hay forma de contactarlas).
"""
import json
import random
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config, db, maritimo

AGENTE = "BuscaPracticas/1.0 (herramienta personal)"

SECTORES_OSM = {
    "company": "Empresa",
    "it": "Informática / IT",
    "consulting": "Consultoría",
    "engineer": "Ingeniería",
    "architect": "Arquitectura",
    "accountant": "Contabilidad",
    "tax_advisor": "Asesoría fiscal",
    "advertising_agency": "Publicidad / Marketing",
    "financial": "Finanzas",
    "insurance": "Seguros",
    "lawyer": "Abogacía",
    "research": "Investigación / I+D",
    "telecommunication": "Telecomunicaciones",
    "logistics": "Logística",
    "estate_agent": "Inmobiliaria",
    "employment_agency": "Agencia de empleo / ETT",
}


def _nada(*_):
    pass


def buscar(cfg, al_progresar=_nada, al_avisar=_nada, cancelado=lambda: False):
    """Busca en todas las ciudades configuradas. Un fallo en una ciudad no detiene las demás."""
    b = cfg["busqueda"]
    if b["fuente"] == "maritimo":
        return maritimo.buscar(b, al_progresar, al_avisar, cancelado)
    if b["fuente"] != "osm":
        return _filtrar(_buscar_ejemplo(b), b)

    ciudades = b["ciudades"]
    todos = []
    for i, ciudad in enumerate(ciudades):
        if cancelado():
            break
        al_progresar(f"Buscando en {ciudad}", i, len(ciudades))
        try:
            encontrados = _filtrar(_buscar_osm(ciudad, b), b)
            al_avisar("info", f"{ciudad}: {len(encontrados)} empresas con email o web.")
            todos += encontrados
        except Exception as ex:
            al_avisar("aviso", f"{ciudad}: no se pudo buscar ({ex}).")
        if i < len(ciudades) - 1:
            time.sleep(1.1)  # las normas de uso de OpenStreetMap piden como mucho 1 petición por segundo
    return todos


def _filtrar(resultados, b):
    resultados = [r for r in resultados if r["tipo"] in b["tipos"]]
    claves = [p.strip().lower() for p in b.get("palabras_clave", "").split(",") if p.strip()]
    if claves:
        resultados = [r for r in resultados
                      if any(c in (r["nombre"] + " " + r["sector"]).lower() for c in claves)]
    # Primero las que tienen email, luego las que tienen web (se les podrá buscar el email)
    resultados.sort(key=lambda r: 0 if r["email"] else 1 if r["web"] else 2)
    return resultados[: int(b.get("max_resultados") or 60)]


def guardar(resultados):
    """Inserta solo las empresas nuevas. Devuelve (nuevas, repetidas)."""
    nuevas = repetidas = 0
    with db.conectar() as con:
        for r in resultados:
            existe = con.execute(
                "SELECT 1 FROM empresas WHERE ref_externa = ? OR (email <> '' AND lower(email) = lower(?))",
                (r["ref_externa"], r["email"]),
            ).fetchone()
            if existe:
                repetidas += 1
                continue
            avisos = [{"tipo": "ucrania", "texto": "Empresa registrada en Ucrania.", "url": r["web"]}] \
                if r["pais"] == "ua" else []
            con.execute(
                """INSERT INTO empresas(nombre, tipo, sector, ciudad, pais, email, web, telefono, fuente,
                                        ref_externa, estado, creado, avisos)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (r["nombre"], r["tipo"], r["sector"], r["ciudad"], r["pais"], r["email"], r["web"],
                 r["telefono"], r["fuente"], r["ref_externa"], "nueva" if r["email"] else "sin_email",
                 db.ahora(), json.dumps(avisos, ensure_ascii=False)),
            )
            nuevas += 1
    return nuevas, repetidas


# ---------------------------------------------------------------- ejemplo

def _buscar_ejemplo(b):
    with open(config.ruta("datos/empresas_ejemplo.json"), encoding="utf-8") as f:
        lista = json.load(f)
    random.shuffle(lista)
    return [{
        "nombre": e["nombre"], "tipo": e["tipo"], "sector": e["sector"],
        "ciudad": e.get("ciudad") or b["ciudades"][0], "pais": e.get("pais", "es"),
        "email": e["email"], "web": e.get("web", ""), "telefono": e.get("telefono", ""),
        "fuente": "ejemplo", "ref_externa": "ejemplo:" + e["email"],
    } for e in lista]


# ---------------------------------------------------------------- OpenStreetMap

# Servidores públicos de Overpass (la API de consultas de OpenStreetMap). Si uno está saturado, se usa otro.
SERVIDORES_OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


def _get_json(url, datos=None, timeout=120):
    req = urllib.request.Request(url, data=datos, headers={"User-Agent": AGENTE})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _overpass(consulta):
    datos = urllib.parse.urlencode({"data": consulta}).encode()
    ultimo_error = None
    for intento, servidor in enumerate(SERVIDORES_OVERPASS * 2):  # dos vueltas por todos los servidores
        try:
            return _get_json(servidor, datos)
        except urllib.error.HTTPError as ex:
            if ex.code not in (429, 502, 503, 504):
                raise
            ultimo_error = ex
        except (urllib.error.URLError, TimeoutError, OSError) as ex:
            ultimo_error = ex
        if intento >= len(SERVIDORES_OVERPASS) - 1:
            time.sleep(5)  # en la segunda vuelta, dar un respiro a los servidores
    raise RuntimeError(f"los servidores de OpenStreetMap están saturados, inténtalo en unos minutos ({ultimo_error})")


def _geocodificar(ciudad):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": ciudad, "format": "json", "limit": 1, "addressdetails": 1, "accept-language": "es"})
    res = _get_json(url)
    if not res:
        raise ValueError("no encuentro esa ciudad en el mapa")
    lugar = res[0]
    nombre = lugar["display_name"].split(",")[0]
    return float(lugar["lat"]), float(lugar["lon"]), lugar.get("address", {}).get("country_code", ""), nombre


def _limpiar_email(valor):
    if not valor:
        return ""
    m = re.search(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", valor)
    return m.group(0) if m else ""


def _buscar_osm(ciudad, b):
    lat, lon, pais, nombre_ciudad = _geocodificar(ciudad)
    radio = int(float(b.get("radio_km") or 10) * 1000)
    tipos = "|".join(SECTORES_OSM)
    zona = f"(around:{radio},{lat},{lon})"
    filtro = f'["office"~"^({tipos})$"]["name"]'
    consulta = f"""
    [out:json][timeout:100];
    (
      nwr{zona}{filtro}["email"];
      nwr{zona}{filtro}["contact:email"];
      nwr{zona}{filtro}["website"];
      nwr{zona}{filtro}["contact:website"];
    );
    out tags center 2000;
    """
    res = _overpass(consulta)

    salida = []
    for el in res.get("elements", []):
        t = el.get("tags", {})
        oficina = t.get("office", "")
        salida.append({
            "nombre": t.get("name", "").strip(),
            "tipo": "agencia" if oficina == "employment_agency" else "empresa",
            "sector": SECTORES_OSM.get(oficina, oficina),
            "ciudad": t.get("addr:city", nombre_ciudad),
            "pais": (t.get("addr:country") or pais or "").lower()[:2],
            "email": _limpiar_email(t.get("email") or t.get("contact:email")),
            "web": t.get("website") or t.get("contact:website") or "",
            "telefono": t.get("phone") or t.get("contact:phone") or "",
            "fuente": "OpenStreetMap",
            "ref_externa": f"osm:{el['type']}/{el['id']}",
        })
    return salida
