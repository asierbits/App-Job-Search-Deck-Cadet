"""Ubicaciones: 'Madrid, Spain' → ('Madrid', 'es'); detección de remoto; ciudades normalizadas."""
import re

from knok.core.text import norm

COUNTRY_NAMES = {
    "es": ["spain", "espana", "españa", "spanien", "espagne", "spagna"],
    "pt": ["portugal"], "fr": ["france", "francia", "frankreich"], "it": ["italy", "italia", "italien"],
    "de": ["germany", "alemania", "deutschland", "allemagne"], "nl": ["netherlands", "the netherlands",
    "holland", "paises bajos", "nederland", "niederlande"], "be": ["belgium", "belgica", "belgique", "belgien"],
    "lu": ["luxembourg", "luxemburgo"], "ie": ["ireland", "irlanda"], "gb": ["united kingdom", "uk", "u.k.",
    "great britain", "england", "scotland", "wales", "reino unido", "inglaterra"], "dk": ["denmark", "dinamarca",
    "danmark"], "se": ["sweden", "suecia", "sverige"], "no": ["norway", "noruega", "norge"], "fi": ["finland",
    "finlandia", "suomi"], "is": ["iceland", "islandia"], "pl": ["poland", "polonia", "polska"], "ee": ["estonia"],
    "lv": ["latvia", "letonia"], "lt": ["lithuania", "lituania"], "gr": ["greece", "grecia"], "cy": ["cyprus",
    "chipre"], "mt": ["malta"], "hr": ["croatia", "croacia"], "si": ["slovenia", "eslovenia"], "ro": ["romania",
    "rumania"], "bg": ["bulgaria"], "ch": ["switzerland", "suiza", "schweiz", "suisse"], "at": ["austria",
    "osterreich", "österreich"], "cz": ["czech republic", "czechia", "republica checa"], "sk": ["slovakia",
    "eslovaquia"], "hu": ["hungary", "hungria"], "us": ["united states", "usa", "u.s.", "us", "estados unidos",
    "united states of america"], "ca": ["canada"], "mx": ["mexico", "méxico"], "ar": ["argentina"],
    "co": ["colombia"], "cl": ["chile"], "pe": ["peru", "perú"], "br": ["brazil", "brasil"],
    "au": ["australia"], "nz": ["new zealand"], "in": ["india"], "sg": ["singapore"], "ae": ["uae",
    "united arab emirates"], "ua": ["ukraine", "ucrania"], "tr": ["turkey", "turkiye", "turquia"],
    "za": ["south africa"], "jp": ["japan"], "il": ["israel"], "mc": ["monaco", "mónaco"],
}
_NAME_TO_ISO = {norm(n): iso for iso, names in COUNTRY_NAMES.items() for n in names}

# Ciudades frecuentes → país (para ubicaciones sin país: "Madrid", "Berlin")
CITY_COUNTRY = {
    "madrid": "es", "barcelona": "es", "valencia": "es", "sevilla": "es", "seville": "es", "bilbao": "es",
    "malaga": "es", "zaragoza": "es", "vigo": "es", "a coruna": "es", "la coruna": "es", "palma": "es",
    "las palmas": "es", "santander": "es", "algeciras": "es", "cadiz": "es", "gijon": "es", "alicante": "es",
    "lisbon": "pt", "lisboa": "pt", "porto": "pt", "paris": "fr", "lyon": "fr", "marseille": "fr",
    "berlin": "de", "munich": "de", "munchen": "de", "hamburg": "de", "hamburgo": "de", "frankfurt": "de",
    "cologne": "de", "koln": "de", "bremen": "de", "amsterdam": "nl", "rotterdam": "nl", "the hague": "nl",
    "den haag": "nl", "utrecht": "nl", "eindhoven": "nl", "brussels": "be", "bruselas": "be", "antwerp": "be",
    "dublin": "ie", "london": "gb", "londres": "gb", "manchester": "gb", "edinburgh": "gb", "glasgow": "gb",
    "copenhagen": "dk", "copenhague": "dk", "stockholm": "se", "gothenburg": "se", "oslo": "no", "bergen": "no",
    "helsinki": "fi", "warsaw": "pl", "krakow": "pl", "athens": "gr", "piraeus": "gr", "el pireo": "gr",
    "limassol": "cy", "valletta": "mt", "zurich": "ch", "geneva": "ch", "vienna": "at", "wien": "at",
    "prague": "cz", "milan": "it", "milano": "it", "rome": "it", "roma": "it", "genoa": "it", "genova": "it",
    "new york": "us", "san francisco": "us", "toronto": "ca", "mexico city": "mx", "buenos aires": "ar",
    "bogota": "co", "santiago": "cl", "lima": "pe", "sao paulo": "br",
}

CITY_ALIASES = {
    "seville": "sevilla", "la coruna": "a coruna", "coruna": "a coruna", "lisbon": "lisboa", "munchen": "munich",
    "muenchen": "munich", "koln": "cologne", "den haag": "the hague", "milano": "milan", "roma": "rome",
    "genova": "genoa", "bruselas": "brussels", "bruxelles": "brussels", "brussel": "brussels",
    "copenhague": "copenhagen", "kobenhavn": "copenhagen", "goteborg": "gothenburg", "wien": "vienna",
    "praha": "prague", "warszawa": "warsaw", "athina": "athens", "el pireo": "piraeus", "londres": "london",
    "hamburgo": "hamburg", "zurich": "zurich",
}

REMOTE_RE = re.compile(r"\b(remote|remoto|teletrabajo|home ?office|work from home|anywhere|en remoto|"
                       r"100% remote|fully remote|t[ée]l[ée]travail)\b", re.I)


def country_from_text(texto: str) -> str:
    n = norm(texto)
    if n in _NAME_TO_ISO:
        return _NAME_TO_ISO[n]
    if re.fullmatch(r"[a-z]{2}", n) and n in COUNTRY_NAMES:
        return n
    return ""


def parse_location(texto: str) -> tuple[str, str, bool]:
    """Devuelve (ciudad, país ISO, remoto)."""
    texto = (texto or "").strip()
    if not texto:
        return "", "", False
    remoto = bool(REMOTE_RE.search(texto))
    partes = [p.strip() for p in re.split(r"[,;/|·–-]| - ", texto) if p.strip()]
    pais, ciudad = "", ""
    for p in reversed(partes):
        c = country_from_text(p)
        if c:
            pais = c
            break
    for p in partes:
        if country_from_text(p) or REMOTE_RE.fullmatch(p.strip()) or re.fullmatch(r"[A-Z]{2}", p):
            continue
        ciudad = p
        break
    if not pais and ciudad:
        pais = CITY_COUNTRY.get(norm(ciudad), "")
    return ciudad, pais, remoto


def city_key(ciudad: str) -> str:
    n = norm((ciudad or "").split(",")[0])
    if REMOTE_RE.search(n):
        return "remote"
    return CITY_ALIASES.get(n, n)


def countries_in_text(texto: str) -> list[str]:
    """Países nombrados en un texto ('authorized to work in the United States?' → ['us'])."""
    n = " " + norm(texto) + " "
    hallados = []
    for nombre in sorted(_NAME_TO_ISO, key=len, reverse=True):
        if len(nombre) <= 3 and nombre not in ("uk", "usa", "uae"):
            continue   # 'us', 'es'… son palabras normales: solo cuentan los nombres
        if re.search(r"(?<![a-z])" + re.escape(nombre) + r"(?![a-z])", n):
            iso = _NAME_TO_ISO[nombre]
            if iso not in hallados:
                hallados.append(iso)
            n = n.replace(nombre, " ")
    return hallados
