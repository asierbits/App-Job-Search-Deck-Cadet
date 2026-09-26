"""Búsqueda de empresas y agencias.

Fuentes:
  - ejemplo: empresas ficticias con correos @example.* (dominios reservados, nunca llegan a nadie)
  - osm:     OpenStreetMap (gratis y sin clave). Busca agencias de empleo y oficinas de empresas
             alrededor de tu ciudad. Muchas no tienen email publicado: aparecen como "sin email"
             y puedes añadírselo a mano desde el panel.
"""
import json
import random
import re
import urllib.parse
import urllib.request

from . import config, db

AGENTE = "BuscaTrabajoPracticas/1.0 (herramienta personal)"

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


def buscar(cfg):
    b = cfg["busqueda"]
    if b["fuente"] == "osm":
        resultados = _buscar_osm(b)
    else:
        resultados = _buscar_ejemplo(b)
    resultados = [r for r in resultados if r["tipo"] in b["tipos"]]
    claves = [p.strip().lower() for p in b.get("palabras_clave", "").split(",") if p.strip()]
    if claves:
        resultados = [r for r in resultados
                      if any(c in (r["nombre"] + " " + r["sector"]).lower() for c in claves)]
    # Primero las que tienen email: son las que se pueden contactar ya
    resultados.sort(key=lambda r: 0 if r["email"] else 1)
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
            con.execute(
                """INSERT INTO empresas(nombre, tipo, sector, ciudad, email, web, telefono, fuente,
                                        ref_externa, estado, creado)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (r["nombre"], r["tipo"], r["sector"], r["ciudad"], r["email"], r["web"], r["telefono"],
                 r["fuente"], r["ref_externa"], "nueva" if r["email"] else "sin_email", db.ahora()),
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
        "ciudad": b["ciudad"], "email": e["email"], "web": e.get("web", ""),
        "telefono": e.get("telefono", ""), "fuente": "ejemplo",
        "ref_externa": "ejemplo:" + e["email"],
    } for e in lista]


# ---------------------------------------------------------------- OpenStreetMap

def _get_json(url, datos=None):
    req = urllib.request.Request(url, data=datos, headers={"User-Agent": AGENTE})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _geocodificar(ciudad):
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": ciudad, "format": "json", "limit": 1})
    res = _get_json(url)
    if not res:
        raise ValueError(f"No encuentro la ciudad '{ciudad}' en OpenStreetMap")
    return float(res[0]["lat"]), float(res[0]["lon"])


def _limpiar_email(valor):
    if not valor:
        return ""
    m = re.search(r"[\w.+-]+@[\w-]+(\.[\w-]+)+", valor)
    return m.group(0) if m else ""


def _buscar_osm(b):
    lat, lon = _geocodificar(b["ciudad"])
    radio = int(float(b.get("radio_km") or 10) * 1000)
    tipos_empresa = "|".join(k for k in SECTORES_OSM if k != "employment_agency")
    consulta = f"""
    [out:json][timeout:80];
    (
      nwr(around:{radio},{lat},{lon})["office"="employment_agency"]["name"];
      nwr(around:{radio},{lat},{lon})["office"~"^({tipos_empresa})$"]["name"];
    );
    out tags center;
    """
    datos = urllib.parse.urlencode({"data": consulta}).encode()
    res = _get_json("https://overpass-api.de/api/interpreter", datos)

    salida = []
    for el in res.get("elements", []):
        t = el.get("tags", {})
        oficina = t.get("office", "")
        salida.append({
            "nombre": t.get("name", "").strip(),
            "tipo": "agencia" if oficina == "employment_agency" else "empresa",
            "sector": SECTORES_OSM.get(oficina, oficina),
            "ciudad": t.get("addr:city", b["ciudad"]),
            "email": _limpiar_email(t.get("email") or t.get("contact:email")),
            "web": t.get("website") or t.get("contact:website") or "",
            "telefono": t.get("phone") or t.get("contact:phone") or "",
            "fuente": "OpenStreetMap",
            "ref_externa": f"osm:{el['type']}/{el['id']}",
        })
    return salida
