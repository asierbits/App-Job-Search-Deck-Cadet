"""Fuentes de navieras europeas.

  - Wikidata: navieras, navieras de cruceros y empresas de transporte marítimo de países europeos
    que tienen web oficial (datos abiertos, consulta gratuita).
  - Directorios: listas públicas de socios de asociaciones de navieros (páginas web o PDF). De cada
    una se sacan las webs de las empresas enlazadas y los emails que aparezcan. Se siguen las páginas
    siguientes si la lista está paginada.

Después, la web de cada naviera se rastrea a fondo (ver webemail.py).
"""
import html
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
import zlib

from . import webemail

# Sin tildes: algunas webs rechazan (403) un User-Agent con caracteres no ASCII
AGENTE = "BuscaPracticas/1.0 (uso personal; busca navieras para un alumno de nautica)"

# Directorios por defecto (se pueden editar en Configuración). Formato: "url" o "url | país".
DIRECTORIOS = [
    "https://www.anave.es/images/informes/empresas_navieras/anave_empresas_navieras.pdf | es",
    "https://www.reederverband.de/der-vdr/mitgliederverzeichnis/ | de",
    "https://www.rederi.no/vare-medlemmer/ | no",
    "https://www.armateursdefrance.org/adherents/ | fr",
    "https://interferry.com/interferry-public-member-list/",
]

# Países europeos: código ISO → identificador en Wikidata
PAISES_WIKIDATA = {
    "es": "Q29", "pt": "Q45", "fr": "Q142", "it": "Q38", "de": "Q183", "nl": "Q55", "be": "Q31", "lu": "Q32",
    "ie": "Q27", "gb": "Q145", "dk": "Q35", "se": "Q34", "no": "Q20", "fi": "Q33", "is": "Q189", "pl": "Q36",
    "ee": "Q191", "lv": "Q211", "lt": "Q37", "gr": "Q41", "cy": "Q229", "mt": "Q233", "hr": "Q224",
    "si": "Q215", "ro": "Q218", "bg": "Q219", "ch": "Q39", "mc": "Q235",
}
PAISES_EUROPA = set(PAISES_WIKIDATA) | {"at", "cz", "sk", "hu", "rs", "me", "al", "ba", "mk", "ua", "ad", "sm", "li"}

# Webs que aparecen en los directorios pero no son navieras
IGNORAR_DOMINIOS = (
    "linkedin", "twitter", "facebook", "instagram", "youtube", "google", "x.com", "flickr", "vimeo",
    "wordpress", "cookie", "apple.com", "microsoft", "adobe", "gstatic", "w3.org", "schema.org", "wp.com",
    "jquery", "cloudflare", "bootstrapcdn", "fonts.", "gravatar", "addtoany", "whatsapp", "xing", "tiktok",
    "pinterest", "mailchimp", "hubspot", "europa.eu", "goo.gl", "bit.ly", "issuu", "spotify", "podcast",
    "wikipedia", "wikimedia", "creativecommons", "cookiebot", "onetrust", "maps.app", "lawai", "t.co",
    "interferryconference", "ecsa.eu", "imo.org", "cruising.org", "ics-shipping", "bimco",
)

# Categorías de Wikidata: naviera (Q1807108), naviera de cruceros (Q946499), sector "transporte por agua" (Q155930)
CONSULTAS_WIKIDATA = [
    ("Naviera", "?item wdt:P31 wd:Q1807108 ."),
    ("Cruceros", "?item wdt:P31 wd:Q946499 ."),
    ("Transporte marítimo", "?item wdt:P452 wd:Q155930 ."),
]


def _get(url, datos=None, cabeceras=None, timeout=60, max_bytes=8_000_000):
    h = {"User-Agent": AGENTE}
    h.update(cabeceras or {})
    req = urllib.request.Request(url, data=datos, headers=h)
    try:
        r = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as ex:
        if not isinstance(getattr(ex, "reason", None), webemail.ssl.SSLCertVerificationError):
            raise
        r = urllib.request.urlopen(req, timeout=timeout, context=webemail._SIN_VERIFICAR)
    with r:
        return r.geturl(), r.headers.get_content_type(), r.read(max_bytes)


def pais_de_dominio(dom, por_defecto=""):
    tld = dom.rsplit(".", 1)[-1].lower()
    tld = "gb" if tld == "uk" else tld
    if len(tld) == 2 and tld != "eu":
        return tld  # dominio de país (puede no ser europeo: se filtra fuera)
    return por_defecto


def nombre_bonito(dom):
    return re.sub(r"[-_]+", " ", dom.split(".")[0]).title()


# Entidades que aparecen en los directorios pero no embarcan alumnos (asociaciones, sindicatos,
# sociedades de clasificación, puertos, astilleros, proveedores, formación…)
RE_NO_NAVIERA = re.compile(
    r"\b(associa\w*|asociaci\w*|federa\w*|organi[sz]ation|organizaci\w*|union|unión|council|consejo|"
    r"chamber|cámara|society|institut\w*|universit\w*|academ\w*|school|escuela|college|ministr\w*|"
    r"authorit\w*|autoridad|port authority|ports\b|puertos\b|register|registro|classification|"
    r"dnv|bureau veritas|lloyd'?s register|rina\b|abs\b|p&i|insurance|seguros|versicherung|bank|banco|"
    r"law|legal|abogados|solicitors|shipyard|astillero\w*|werft|naval architect\w*|design|software|"
    r"systems|solutions|consult\w*|broker\w*|conference|magazine|news|media|journal|interferry)\b",
    re.I)


def es_naviera(nombre):
    return not RE_NO_NAVIERA.search(nombre or "")


def _web_valida(url):
    d = webemail.dominio(url)
    return d and not any(s in d for s in IGNORAR_DOMINIOS)


# ---------------------------------------------------------------- Wikidata

def buscar_wikidata(al_avisar=lambda *a: None):
    qids = " ".join("wd:" + q for q in PAISES_WIKIDATA.values())
    iso_de_qid = {q: iso for iso, q in PAISES_WIKIDATA.items()}
    resultados = {}
    for categoria, patron in CONSULTAS_WIKIDATA:
        consulta = f"""SELECT ?item ?itemLabel ?web ?pais WHERE {{
          VALUES ?pais {{ {qids} }}
          {patron}
          ?item wdt:P17 ?pais ; wdt:P856 ?web .
          FILTER NOT EXISTS {{ ?item wdt:P576 ?disuelta }}
          SERVICE wikibase:label {{ bd:serviceParam wikibase:language "es,en". }}
        }}"""
        datos = urllib.parse.urlencode({"query": consulta}).encode()
        filas = None
        for intento in range(3):
            try:
                _, _, cuerpo = _get("https://query.wikidata.org/sparql", datos,
                                    {"Accept": "application/sparql-results+json"}, timeout=90)
                filas = json.loads(cuerpo)["results"]["bindings"]
                break
            except urllib.error.HTTPError as ex:
                if ex.code not in (429, 500, 502, 503, 504) or intento == 2:
                    al_avisar("aviso", f"Wikidata ({categoria}): no disponible ahora ({ex.code}).")
                    break
                time.sleep(min(int(ex.headers.get("Retry-After") or 15), 60))
            except Exception as ex:
                al_avisar("aviso", f"Wikidata ({categoria}): {ex}")
                break
        for f in filas or []:
            web = f["web"]["value"]
            if not _web_valida(web):
                continue
            dom = webemail.dominio(web)
            nombre = f["itemLabel"]["value"]
            if re.fullmatch(r"Q\d+", nombre):
                nombre = nombre_bonito(dom)
            resultados.setdefault(dom, {
                "nombre": nombre, "web": web, "email": "", "sector": categoria,
                "pais": iso_de_qid.get(f["pais"]["value"].rsplit("/", 1)[-1], ""),
                "fuente": "Wikidata",
            })
        time.sleep(2)  # ser amables con el servicio público de consultas
    return list(resultados.values())


# ---------------------------------------------------------------- directorios

def _limpiar_nombre(texto, dom):
    t = re.sub(r"<[^>]+>", " ", html.unescape(texto))
    t = re.sub(r"\b(website|webside|web|www|homepage|hjemmeside|webseite|site|visit|besøk|besuchen|"
               r"read more|mehr|voir|ver más|link)\b", " ", t, flags=re.I)
    t = re.sub(r"\s+", " ", t).strip(" -–|:·")
    if len(t) < 3 or "." in t and " " not in t or t.lower().startswith("http"):
        return nombre_bonito(dom)
    return t[:80]


def _directorio_html(url, texto, pais_def):
    host = webemail.dominio(url)
    candidatos = {}
    for href, txt in webemail.RE_ENLACE.findall(texto):
        href = html.unescape(href).strip()
        if not href.startswith("http") or not _web_valida(href):
            continue
        dom = webemail.dominio(href)
        if dom == host or dom.endswith("." + host) or host.endswith("." + dom):
            continue
        candidatos.setdefault(dom, {"nombre": _limpiar_nombre(txt, dom), "web": href, "email": ""})
    # Emails de la página: se asignan a la empresa con el mismo nombre de dominio
    for e in webemail.extraer_emails(texto):
        base = e.split("@")[1].split(".")[0]
        for dom, c in candidatos.items():
            if dom.split(".")[0] == base and not c["email"]:
                c["email"] = e
    return candidatos


def _directorio_pdf(datos):
    """Webs (enlaces /URI) y emails de un PDF, sin librerías: también dentro de los bloques comprimidos."""
    bloques = [datos]
    for m in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", datos, re.S):
        try:
            bloques.append(zlib.decompress(m.group(1)))
        except Exception:
            pass
    todo = b"\n".join(bloques).decode("latin-1")
    webs = [u for u in re.findall(r"/URI\s*\((https?://[^)]+)\)", todo) if _web_valida(u)]
    emails = webemail.extraer_emails(" ".join(re.findall(r"/URI\s*\(mailto:([^)]+)\)", todo)) + " " + todo)
    candidatos = {}
    for w in webs:
        dom = webemail.dominio(w)
        raiz = urllib.parse.urlunsplit(urllib.parse.urlsplit(w)[:2] + ("/", "", ""))
        candidatos.setdefault(dom, {"nombre": nombre_bonito(dom), "web": raiz, "email": ""})
    for e in sorted(emails):
        dom_e = e.split("@")[1]
        if any(s in dom_e for s in IGNORAR_DOMINIOS):
            continue
        base = dom_e.split(".")[0]
        destino = next((c for d, c in candidatos.items() if d.split(".")[0] == base), None)
        if destino is None:  # empresa con email pero sin web enlazada: su web será la del dominio del email
            destino = candidatos.setdefault(dom_e, {"nombre": nombre_bonito(dom_e), "web": "https://" + dom_e + "/", "email": ""})
        if not destino["email"] or webemail.puntuacion(e, destino["web"]) > webemail.puntuacion(destino["email"], destino["web"]):
            destino["email"] = e
    return candidatos


RE_NUM_PAGINA = re.compile(r"([?&][\w-]*page[\w-]*=|/page/|/seite/|/pagina/)(\d+)", re.I)


def _pagina_siguiente(texto, url):
    """Enlace a la página siguiente de una lista paginada (misma web): por número de página
    (?page=3, ?query-1-page=3, /page/3…) o por un enlace «siguiente / weiter / next»."""
    host = webemail.dominio(url)
    m = RE_NUM_PAGINA.search(url)
    actual = int(m.group(2)) if m else 1
    mejor = None
    for href, _ in webemail.RE_ENLACE.findall(texto):
        h = urllib.parse.urljoin(url, html.unescape(href))
        m = RE_NUM_PAGINA.search(h)
        if m and webemail.dominio(h) == host and int(m.group(2)) == actual + 1:
            mejor = h
            break
    if mejor:
        return mejor
    for href, txt in webemail.RE_ENLACE.findall(texto):
        t = re.sub(r"<[^>]+>", "", txt).strip().lower()
        h = html.unescape(href)
        if t in ("›", "»", ">", "next", "siguiente", "weiter", "nächste", "suivant", "neste", "volgende") or \
                re.search(r'rel=["\']next', h):
            siguiente = urllib.parse.urljoin(url, h)
            if webemail.dominio(siguiente) == host and siguiente != url:
                return siguiente
    return None


def buscar_directorio(entrada, al_avisar=lambda *a: None, max_paginas=30):
    url, _, pais_def = entrada.partition("|")
    url, pais_def = url.strip(), pais_def.strip().lower()[:2]
    partes = urllib.parse.urlsplit(url)
    robots = urllib.robotparser.RobotFileParser()
    try:
        robots.parse(_get(f"{partes.scheme}://{partes.netloc}/robots.txt", timeout=20)[2]
                     .decode("utf-8", "ignore").splitlines())
    except Exception:
        robots.parse([])
    if not robots.can_fetch(AGENTE, url):
        al_avisar("aviso", f"{partes.netloc}: su robots.txt no permite leer esa página, se omite.")
        return []

    candidatos, visitadas, actual = {}, set(), url
    while actual and actual not in visitadas and len(visitadas) < max_paginas:
        visitadas.add(actual)
        final, tipo, datos = _get(actual)
        if tipo == "application/pdf" or datos[:5] == b"%PDF-":
            candidatos.update({k: v for k, v in _directorio_pdf(datos).items() if k not in candidatos})
            break
        texto = datos.decode("utf-8", "ignore")
        for dom, c in _directorio_html(final, texto, pais_def).items():
            candidatos.setdefault(dom, c)
        actual = _pagina_siguiente(texto, final)
        if actual:
            time.sleep(1)

    salida = []
    propia = webemail.dominio(url).split(".")[0]
    for dom, c in candidatos.items():
        if dom.split(".")[0] == propia:
            continue  # la propia asociación no es una naviera
        pais = pais_de_dominio(dom, pais_def)
        if pais and pais not in PAISES_EUROPA:
            continue  # directorios mundiales (p. ej. Interferry): solo Europa
        c.update(pais=pais, sector="Naviera", fuente=partes.netloc.removeprefix("www."))
        salida.append(c)
    return salida


# ---------------------------------------------------------------- todo junto

def buscar(b, al_progresar=lambda *a: None, al_avisar=lambda *a: None, cancelado=lambda: False):
    fuentes = []
    if b.get("usar_wikidata", True):
        fuentes.append(("Wikidata", lambda: buscar_wikidata(al_avisar)))
    for entrada in b.get("directorios") or []:
        if entrada.strip():
            fuentes.append((entrada.split("|")[0].strip(), lambda e=entrada: buscar_directorio(e, al_avisar)))

    empresas = {}
    for i, (nombre, fn) in enumerate(fuentes):
        if cancelado():
            break
        etiqueta = webemail.dominio(nombre) or nombre
        al_progresar(f"Leyendo {etiqueta}", i, len(fuentes))
        try:
            lista = fn()
            al_avisar("info", f"{etiqueta}: {len(lista)} navieras.")
        except Exception as ex:
            al_avisar("aviso", f"{etiqueta}: no se pudo leer ({ex}).")
            continue
        descartadas = [c for c in lista if not es_naviera(c["nombre"])]
        if descartadas:
            al_avisar("info", f"{etiqueta}: {len(descartadas)} descartadas por no ser navieras "
                              f"(asociaciones, proveedores, puertos…).")
        for c in lista:
            if not es_naviera(c["nombre"]):
                continue
            dom = webemail.dominio(c["web"])
            clave = dom.split(".")[0] if dom.count(".") <= 1 else dom  # balearia.com y balearia.es = misma
            previo = empresas.get(clave)
            if previo is None:
                empresas[clave] = c
            else:  # la misma naviera en varias fuentes: completar datos
                if not previo["email"] and c["email"]:
                    previo["email"] = c["email"]
                if not previo["pais"] and c["pais"]:
                    previo["pais"] = c["pais"]
                if previo["nombre"] == nombre_bonito(webemail.dominio(previo["web"])) and \
                        c["nombre"] != nombre_bonito(dom):
                    previo["nombre"] = c["nombre"]

    return [{
        "nombre": c["nombre"], "tipo": "empresa", "sector": c["sector"], "ciudad": "",
        "pais": c["pais"], "email": c["email"], "web": c["web"], "telefono": "",
        "fuente": c["fuente"], "ref_externa": "dom:" + clave,
    } for clave, c in empresas.items()]
