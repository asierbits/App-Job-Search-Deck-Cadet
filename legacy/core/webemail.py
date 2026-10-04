"""Rastrea la web de una empresa para encontrar su mejor email de contacto para una candidatura.

Visita la portada y las páginas más prometedoras del mismo dominio (tripulación, cadetes, empleo,
contacto, aviso legal / Impressum…), respetando robots.txt. Además apunta:
  - la página de empleo / tripulación (para registrarse si solo aceptan formulario),
  - si la web menciona programas de cadetes / alumnos,
  - el nombre de la empresa según su propia web.
"""
import html
import re
import ssl
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser

# Sin tildes: algunas webs rechazan (403) un User-Agent con caracteres no ASCII
AGENTE = "BuscaPracticas/1.0 (busca emails de contacto publicados; uso personal)"
MAX_PAGINAS = 8
TIEMPO_MAX_POR_WEB = 45  # segundos: una web lenta no debe atascar el rastreo

RE_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24}")
RE_ENLACE = re.compile(r"""<a\b[^>]*?href\s*=\s*["']([^"'#]+)["'][^>]*>(.*?)</a>""", re.I | re.S)
RE_CFEMAIL = re.compile(r"""data-cfemail\s*=\s*["']([0-9a-fA-F]+)["']""")
RE_TITULO = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
RE_SITENAME = re.compile(r"""<meta[^>]+property=["']og:site_name["'][^>]+content=["']([^"']+)["']""", re.I)

# Páginas donde suele estar el email, por orden de interés (se busca en la ruta y en el texto del enlace)
PAGINAS_CLAVE = [
    "cadet", "cadete", "kadett", "trainee", "alumno", "seafarer", "crewing", "crew", "tripulacion",
    "tripulación", "embarque", "sea-career", "career-at-sea", "careers-at-sea", "working-at-sea",
    "fleet-personnel", "marine-personnel", "seagoing", "offshore-career",
    "career", "careers", "karriere", "jobs", "job", "empleo", "trabaja", "join", "vacanc", "recruit",
    "impressum", "imprint", "contact", "kontakt", "contacto", "contatto", "contato", "kontakt-oss",
    "aviso-legal", "legal", "mentions-legales", "about", "nosotros", "ueber-uns", "uber-uns", "om-oss",
]
# Buzones preferidos, del más al menos específico para un alumno de puente
PREFERIDOS = ["cadet", "cadets", "crewing", "crew", "manning", "seafarer", "marinehr", "marine.hr",
              "tripulacion", "flota", "fleet", "personal.flota", "jobs", "job", "careers", "career",
              "karriere", "bewerbung", "empleo", "rrhh", "hr", "recruiting", "recruitment", "talent",
              "seleccion", "people", "personal", "practicas", "internship", "trainee"]
GENERICOS = ["info", "contact", "contacto", "kontakt", "hello", "hola", "office", "mail", "hallo",
             "bonjour", "post", "firmapost", "admin", "general", "reception"]
DESCARTAR = ["noreply", "no-reply", "donotreply", "privacy", "datenschutz", "dpo", "gdpr", "rgpd",
             "abuse", "webmaster", "postmaster", "sentry", "example", "wixpress", "yourname", "tuemail",
             "newsletter", "unsubscribe", "domain.com", "email.com", "sentry.io", "booking", "reservas",
             "reservations", "tickets", "billetes", "invoice", "factura", "accounts", "press", "prensa",
             "media@", "compliance", "whistle", "ethics", "denuncia", "investor", "ir@"]
PROVEEDORES_GRATIS = {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com", "yahoo.es", "icloud.com",
                      "gmx.de", "gmx.net", "web.de", "t-online.de", "orange.fr", "free.fr", "libero.it",
                      "hotmail.es", "outlook.es", "live.com", "protonmail.com", "wanadoo.fr", "online.no"}
EXTENSIONES_NO_HTML = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif", ".pdf", ".zip", ".mp4",
                       ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".ics")
# Buzones comerciales: válidos, pero peores que info@ para una candidatura
COMERCIALES = ["comercial", "sales", "ventas", "booking", "chartering", "chart", "operations", "operaciones",
               "carga", "cargo", "freight", "fletes", "compras", "purchas", "marketing", "export", "import",
               "traffic", "trafico", "tráfico", "customer", "cliente", "atencion"]
# Rutas que nunca son la página de empleo aunque su título lo parezca
NO_EMPLEO = ("/blog", "/news", "/noticias", "/press", "/prensa", "/actualidad", "/aktuelles", "/nyheter", "/actualites")
# Términos que indican que embarcan alumnos / cadetes. Se buscan en el texto visible de la web, sin
# distinguir mayúsculas ni tildes. El primero de cada par es cómo se muestra en el panel.
TERMINOS_CADETE = [
    ("alumno de puente en prácticas", ["alumno de puente en practicas", "alumnos de puente en practicas"]),
    ("alumno de puente", ["alumno de puente", "alumnos de puente"]),
    ("alumno en prácticas", ["alumno en practicas", "alumnos en practicas"]),
    ("alumno", ["alumno", "alumnos"]),
    ("deck cadet", ["deck cadet"]),
    ("deck apprentice", ["deck apprentice"]),
    ("engine cadet (máquinas)", ["engine cadet", "engineer cadet", "alumno de maquinas", "alumnos de maquinas"]),
    ("cadet", ["cadet", "cadets", "cadetship", "cadete", "cadetes"]),
    ("trainee officer", ["trainee officer", "officer trainee", "deck trainee"]),
    ("kadett / praktikant", ["kadett", "praktikant"]),
    ("élève officier", ["eleve officier"]),
    ("allievo ufficiale", ["allievo ufficiale"]),
]

# Empleo embarcado / offshore: si la página de empleo habla de trabajar a bordo (aunque no mencione alumnos)
EMPLEO_MAR = "empleo embarcado / offshore"  # se guarda junto a las menciones con este nombre
EMPLEO_MAR_RE = re.compile(
    r"\b(seafarers?|seagoing|sea staff|sea-based|sea based|at sea|onboard|on board|offshore|crew members?|"
    r"crewing|marine crew|deck officers?|officer of the watch|able seam[ae]n|ratings|sea careers?|"
    r"career at sea|careers at sea|working at sea|embarcad[oa]s?|a bordo|tripulacion|tripulantes?|"
    r"oficial(?:es)? de puente|personal de flota|personal embarcado|seefahrend\w*|an bord|"
    r"personnel navigant|navigants?|a bord|bordpersonal|sjofolk|til sjos)\b")


# Avisos: señales para revisar una empresa antes de escribirle
AVISOS = {
    # MLC 2006 (regla 1.4): las agencias no pueden cobrar a los marinos por buscarles embarque
    # (solo se busca en páginas de empleo/tripulación: en las de billetes de ferry «fee» es otra cosa)
    "cobro": [r"registration fee", r"processing fee", r"placement fee", r"agency fee",
              r"application fee", r"recruitment fee", r"training fee", r"manning fee", r"crewing fee",
              r"embarkation fee", r"fee for (?:the )?(?:placement|employment|embarkation|registration)",
              r"pay (?:a|the) fee",
              r"tasa de (?:inscripcion|registro|gestion)", r"cuota de (?:inscripcion|registro|alta)",
              r"gastos de gestion", r"pago previo", r"precio del embarque", r"coste del embarque",
              r"debe(?:ra|s)? (?:abonar|pagar)", r"vermittlungsgebuhr", r"anmeldegebuhr", r"frais d'inscription"],
    # Empresa / oficina en Ucrania o puertos ucranianos. No salta por la nacionalidad de la tripulación
    # («ukrainian officers»), que no indica que la empresa sea de allí.
    "ucrania": [r"\bodes{1,2}a\b", r"\bmykolaiv\b", r"\bnikolaev\b", r"\bizmail\b", r"\bchornomorsk\b",
                r"\bkherson\b", r"\bmariupol\b", r"\bberdyansk\b", r"\bkyiv\b", r"\bkiev\b",
                r"\b(?:in|from|based in|office in|offices in) ukraine\b", r"\bukraine (?:office|branch|ltd|llc)\b",
                r"\bukrainian (?:company|shipowner|owner|agency|crewing|manning|flag)\b",
                r"\ben ucrania\b", r"\bempresa ucraniana\b", r"\bagencia ucraniana\b"],
    "mar_negro": [r"\bblack sea\b", r"\bmar negro\b", r"\bschwarze[sn]? meer\b", r"\bmer noire\b", r"\bmar nero\b",
                  r"\bsea of azov\b", r"\bmar de azov\b", r"\bazov\b", r"\bnovorossiysk\b", r"\bkerch\b",
                  r"\bsevastopol\b", r"\bcrimea\b", r"\bcrimea\b", r"\bconflict zone\b", r"\bwar risk area\b",
                  r"\bhigh risk area\b", r"\bzona de conflicto\b"],
}
AVISOS_RE = {tipo: re.compile("|".join(p), re.I) for tipo, p in AVISOS.items()}


def _sin_tildes(texto):
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").lower()


def texto_visible(html_pagina):
    """El texto que ve una persona (sin scripts, estilos ni etiquetas), normalizado sin tildes."""
    t = re.sub(r"<(script|style|noscript|svg)\b.*?</\1>", " ", html_pagina, flags=re.I | re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    return re.sub(r"\s+", " ", _sin_tildes(t))


def buscar_terminos(texto):
    """Términos de cadetes que aparecen como palabras completas en el texto (ya normalizado)."""
    hallados = []
    for etiqueta, variantes in TERMINOS_CADETE:
        if any(re.search(r"\b" + re.escape(v) + r"\b", texto) for v in variantes):
            hallados.append(etiqueta)
    return hallados


def buscar_avisos(texto, url, pagina_empleo=False):
    """Avisos del texto con la frase que los provoca, para que la persona juzgue si son reales."""
    avisos = []
    for tipo, patron in AVISOS_RE.items():
        if tipo == "cobro" and not pagina_empleo:
            continue
        m = patron.search(texto)
        if m:
            ini, fin = max(0, m.start() - 90), min(len(texto), m.end() + 90)
            avisos.append({"tipo": tipo, "texto": ("…" if ini else "") + texto[ini:fin].strip() + ("…" if fin < len(texto) else ""),
                           "url": url})
    return avisos
# Portales de empleo / tripulación de terceros a los que suelen enlazar
PORTALES = ["crewportal", "crew-portal", "seagull", "workday", "successfactors", "teamtailor", "recruitee",
            "greenhouse.io", "lever.co", "smartrecruiters", "personio", "jobs.", "careers.", "join.com",
            "applytojob", "bamboohr", "taleo", "icims", "softgarden", "jobylon", "hrmos", "crewing"]

# Muchas webs pequeñas no envían completa su cadena de certificados: los navegadores lo arreglan solos,
# Python no. Como aquí solo se LEEN páginas públicas, se reintenta sin verificar el certificado.
# (Nunca se hace esto al enviar correo ni al hablar con Gmail.)
_SIN_VERIFICAR = ssl.create_default_context()
_SIN_VERIFICAR.check_hostname = False
_SIN_VERIFICAR.verify_mode = ssl.CERT_NONE


def _descargar(url, tipos=("text/html",), max_bytes=1_500_000):
    try:
        return _abrir(url, tipos, max_bytes, None)
    except urllib.error.URLError as ex:
        if isinstance(ex.reason, ssl.SSLCertVerificationError):
            return _abrir(url, tipos, max_bytes, _SIN_VERIFICAR)
        raise


def _abrir(url, tipos, max_bytes, contexto):
    req = urllib.request.Request(url, headers={"User-Agent": AGENTE, "Accept": "text/html,*/*;q=0.5",
                                               "Accept-Language": "es,en;q=0.8,de;q=0.6,fr;q=0.5"})
    with urllib.request.urlopen(req, timeout=15, context=contexto) as r:
        tipo = r.headers.get_content_type()
        if not any(tipo.startswith(t) for t in tipos):
            return r.geturl(), ""
        datos = r.read(max_bytes)
        return r.geturl(), datos.decode(r.headers.get_content_charset() or "utf-8", errors="ignore")


def dominio(url):
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def _decodificar_cloudflare(hexa):
    clave = int(hexa[:2], 16)
    return "".join(chr(int(hexa[i:i + 2], 16) ^ clave) for i in range(2, len(hexa), 2))


def extraer_emails(texto):
    texto = html.unescape(texto)
    extra = [_decodificar_cloudflare(h) for h in RE_CFEMAIL.findall(texto)]
    # Ofuscaciones típicas: "info [at] empresa [dot] de", "rrhh(arroba)empresa.es"
    texto = re.sub(r"\s*[\[\(\{]\s*(?:at|arroba|ät)\s*[\]\)\}]\s*", "@", texto, flags=re.I)
    texto = re.sub(r"\s*[\[\(\{]\s*(?:dot|punto|punkt|point)\s*[\]\)\}]\s*", ".", texto, flags=re.I)
    encontrados = set()
    for e in RE_EMAIL.findall(texto) + extra:
        e = e.strip(".").lower()
        if e.endswith(EXTENSIONES_NO_HTML) or any(d in e for d in DESCARTAR):
            continue
        encontrados.add(e)
    return encontrados


def _prioridad(url, texto_enlace):
    """0 = lo más interesante. None = no merece la pena visitarla."""
    ruta = urllib.parse.urlsplit(url).path.lower()
    texto = re.sub(r"<[^>]+>", " ", texto_enlace).lower()
    for i, p in enumerate(PAGINAS_CLAVE):
        if p in ruta or p in texto:
            return i
    return None


def _enlaces(texto, base, dom):
    """Enlaces internos interesantes (ordenados) y enlaces a portales de empleo externos."""
    internos, portales = [], []
    for href, txt in RE_ENLACE.findall(texto):
        href = html.unescape(href).strip()
        if href.startswith(("mailto:", "tel:", "javascript:")):
            continue
        url = urllib.parse.urljoin(base, href).split("#")[0]
        if not url.startswith("http") or url.lower().split("?")[0].endswith(EXTENSIONES_NO_HTML):
            continue
        d = dominio(url)
        prioridad = _prioridad(url, txt)
        if d == dom or d.endswith("." + dom):
            if prioridad is not None:
                internos.append((prioridad, url))
        elif prioridad is not None and prioridad < PAGINAS_CLAVE.index("impressum") and \
                any(p in url.lower() for p in PORTALES):
            portales.append((prioridad, url))
    ordenar = lambda lista: list(dict.fromkeys(u for _, u in sorted(lista)))
    return ordenar(internos), ordenar(portales)


def _robots(inicio):
    rp = urllib.robotparser.RobotFileParser()
    try:
        _, texto = _descargar(urllib.parse.urljoin(inicio, "/robots.txt"), tipos=("text/",), max_bytes=300_000)
        rp.parse(texto.splitlines())
    except Exception:
        rp.parse([])  # sin robots.txt accesible: todo permitido
    return rp


def _puntuar(email, dom):
    local, _, d = email.partition("@")
    propio = d == dom or d.endswith("." + dom) or dom.endswith("." + d) or \
        d.split(".")[0] == dom.split(".")[0]  # mismo nombre con otro dominio (.com / .es)
    if not propio and d not in PROVEEDORES_GRATIS:
        return None  # probablemente de otra empresa (la agencia que hizo la web, un proveedor…)
    puntos = 10 if propio else 3
    if d == dom or d.endswith("." + dom):
        puntos += 2  # el dominio exacto de la web (no una filial de otro país)
    for i, p in enumerate(PREFERIDOS):
        if local == p or local.startswith(p) or ("." + p) in local or ("-" + p) in local:
            return puntos + 12 - min(i, 6)  # los de tripulación/cadetes puntúan más que los de RR. HH.
    if any(c in local for c in COMERCIALES):
        return puntos - 5
    if any(g == local or local.startswith(g) for g in GENERICOS):
        return puntos + 3
    if re.fullmatch(r"[a-z]+[._-][a-z]+", local):
        return puntos - 2  # parece personal (nombre.apellido): mejor un buzón general
    return puntos


def nombre_de_la_web(texto):
    m = RE_SITENAME.search(texto) or RE_TITULO.search(texto)
    if not m:
        return ""
    titulo = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip(" |–—-:·")
    partes = [p.strip() for p in re.split(r"\s[|–—\-:·]\s", titulo) if 2 < len(p.strip()) < 60]
    comunes = ("home", "inicio", "startseite", "accueil", "welcome", "bienvenid", "forside", "etusivu")
    partes = [p for p in partes if not p.lower().startswith(comunes)]
    return min(partes, key=len) if partes else ""


def rastrear(web):
    """Devuelve un dict con: email, email_fuente, web_empleo, cadetes (bool) y nombre (de la web)."""
    res = {"email": None, "email_fuente": None, "web_empleo": None, "cadetes": False, "nombre": "",
           "bloqueada": False, "menciones": [], "avisos": []}
    if not web:
        return res
    if not re.match(r"https?://", web, re.I):
        web = "https://" + web
    dom = dominio(web)
    if not dom:
        return res
    limite = time.monotonic() + TIEMPO_MAX_POR_WEB
    robots = _robots(web)
    pendientes, visitadas, hallados = [web], set(), {}
    portada_leida = False

    while pendientes and len(visitadas) < MAX_PAGINAS and time.monotonic() < limite:
        url = pendientes.pop(0)
        if url in visitadas or not robots.can_fetch(AGENTE, url):
            continue
        visitadas.add(url)
        try:
            final, texto = _descargar(url)
        except urllib.error.HTTPError as ex:
            if not portada_leida and ex.code in (401, 403, 429):
                res["bloqueada"] = True  # la web no deja leerla a programas: se respeta, mírala a mano
                break
            continue
        except Exception:
            if not portada_leida and url.startswith("https://"):
                pendientes.insert(0, "http://" + url[8:])  # algunas webs pequeñas no tienen https
            continue
        if not texto:
            continue
        if not portada_leida:
            portada_leida = True
            dom = dominio(final) or dom  # por si redirige a otro dominio (p. ej. .com → .de)
            res["nombre"] = nombre_de_la_web(texto)
        internos, portales = _enlaces(texto, final, dom)
        # Las páginas nuevas más interesantes, primero (así se llega de «Carreras» a «Cadetes»)
        nuevos = [u for u in internos if u not in visitadas and u not in pendientes]
        pendientes = sorted(pendientes + nuevos, key=lambda u: _prioridad(u, "") if _prioridad(u, "") is not None else 99)

        ruta = urllib.parse.urlsplit(final).path.lower()
        es_empleo = any(p in ruta for p in PAGINAS_CLAVE[:PAGINAS_CLAVE.index("impressum")]) and \
            not any(n in ruta for n in NO_EMPLEO)
        visible = texto_visible(texto)
        for t in buscar_terminos(visible):
            if t not in res["menciones"]:
                res["menciones"].append(t)
        tipos_vistos = {a["tipo"] for a in res["avisos"]}
        res["avisos"] += [a for a in buscar_avisos(visible, final, es_empleo) if a["tipo"] not in tipos_vistos]
        res["cadetes"] = any(m != EMPLEO_MAR for m in res["menciones"])
        if es_empleo:
            a_bordo = bool(EMPLEO_MAR_RE.search(visible))
            if a_bordo and EMPLEO_MAR not in res["menciones"]:
                res["menciones"].append(EMPLEO_MAR)
            # El enlace «empleo» apunta a la página de trabajo a bordo si la hay (mejor que una general)
            if not res["web_empleo"] or (a_bordo and not res.get("empleo_es_a_bordo")):
                res["web_empleo"] = final
                res["empleo_es_a_bordo"] = a_bordo
        if portales and not res["web_empleo"]:
            res["web_empleo"] = portales[0]

        for e in extraer_emails(texto):
            puntos = _puntuar(e, dom)
            if puntos is None:
                continue
            if es_empleo:
                puntos += 2  # encontrado en la página de empleo / tripulación
            if e not in hallados or hallados[e][0] < puntos:
                hallados[e] = (puntos, final)
        if any(p >= 22 for p, _ in hallados.values()):
            break  # ya tenemos un buzón de tripulación / cadetes del propio dominio

    if hallados:
        email, (_, donde) = max(hallados.items(), key=lambda kv: kv[1][0])
        res.update(email=email, email_fuente=donde)
    res["leida"] = portada_leida  # False si la web no respondió (caída, sin conexión…)
    return res


def puntuacion(email, web):
    """Para comparar un email ya conocido (p. ej. de un directorio) con el que encuentre el rastreo."""
    return _puntuar(email, dominio(web if re.match(r"https?://", web or "", re.I) else "https://" + (web or ""))) or 0


def buscar_email(web):
    """Compatibilidad: (email, url_donde_se_encontró) o (None, None)."""
    r = rastrear(web)
    return r["email"], r["email_fuente"]
