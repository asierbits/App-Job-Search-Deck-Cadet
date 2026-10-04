"""Catálogo de sectores para crear un nicho propio sin saber de OpenStreetMap.

Cada sector dice qué etiquetas de OpenStreetMap tienen las empresas de ese tipo (las que se buscan
alrededor de las ciudades de la búsqueda) y qué buzones suelen usar para empleo. Solo etiquetas
documentadas en el wiki de OSM (https://wiki.openstreetmap.org/wiki/Map_features).
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Sector:
    id: str
    es: str
    en: str
    osm: dict[str, tuple[str, ...]]
    group: str
    agency: bool = False                                   # sus empresas son agencias (ETT, selección…)
    mailboxes: tuple[str, ...] = ()                        # buzones típicos de empleo del sector
    labels: dict[str, str] = field(default_factory=dict)   # valor OSM → etiqueta legible


SECTORS: list[Sector] = [
    # --- oficinas y servicios profesionales
    Sector("tecnologia", "Tecnología y software", "Technology and software", {"office": ("it", "telecommunication")},
           "Oficinas", mailboxes=("jobs", "careers", "talent"), labels={"it": "Informática / IT", "telecommunication": "Telecomunicaciones"}),
    Sector("consultoria", "Consultoría", "Consulting", {"office": ("consulting",)}, "Oficinas", labels={"consulting": "Consultoría"}),
    Sector("ingenieria", "Ingeniería", "Engineering", {"office": ("engineer", "surveyor", "geodesist")}, "Oficinas",
           labels={"engineer": "Ingeniería", "surveyor": "Topografía", "geodesist": "Geodesia"}),
    Sector("arquitectura", "Arquitectura e interiorismo", "Architecture and interior design", {"office": ("architect",), "shop": ("interior_decoration",)},
           "Oficinas", labels={"architect": "Arquitectura", "interior_decoration": "Interiorismo"}),
    Sector("legal", "Abogados y notarías", "Law firms and notaries", {"office": ("lawyer", "notary")}, "Oficinas",
           labels={"lawyer": "Abogacía", "notary": "Notaría"}),
    Sector("finanzas", "Contabilidad, asesorías y finanzas", "Accounting, advisory and finance",
           {"office": ("accountant", "tax_advisor", "financial", "financial_advisor")}, "Oficinas",
           labels={"accountant": "Contabilidad", "tax_advisor": "Asesoría fiscal", "financial": "Finanzas", "financial_advisor": "Asesoría financiera"}),
    Sector("seguros", "Seguros", "Insurance", {"office": ("insurance",)}, "Oficinas", labels={"insurance": "Seguros"}),
    Sector("marketing", "Marketing, publicidad y medios", "Marketing, advertising and media",
           {"office": ("advertising_agency", "newspaper"), "studio": ("radio", "television", "video", "audio")}, "Oficinas",
           labels={"advertising_agency": "Publicidad / Marketing", "newspaper": "Prensa", "radio": "Radio", "television": "Televisión",
                   "video": "Productora audiovisual", "audio": "Estudio de sonido"}),
    Sector("inmobiliaria", "Inmobiliarias", "Real estate", {"office": ("estate_agent", "property_management")}, "Oficinas",
           labels={"estate_agent": "Inmobiliaria", "property_management": "Administración de fincas"}),
    Sector("logistica", "Logística y transporte", "Logistics and transport", {"office": ("logistics", "courier", "moving_company")}, "Oficinas",
           labels={"logistics": "Logística", "courier": "Mensajería", "moving_company": "Mudanzas"}),
    Sector("energia", "Energía", "Energy", {"office": ("energy_supplier",)}, "Oficinas", labels={"energy_supplier": "Energía"}),
    Sector("investigacion", "Investigación e I+D", "Research and R&D", {"office": ("research",), "amenity": ("research_institute",)},
           "Oficinas", mailboxes=("phd", "research", "jobs"), labels={"research": "Investigación / I+D", "research_institute": "Instituto de investigación"}),
    Sector("ong", "ONG, fundaciones y asociaciones", "NGOs, foundations and associations",
           {"office": ("ngo", "foundation", "association", "charity")}, "Oficinas",
           mailboxes=("voluntariado", "volunteer"), labels={"ngo": "ONG", "foundation": "Fundación", "association": "Asociación", "charity": "Organización benéfica"}),
    Sector("publico", "Administración pública", "Public administration", {"office": ("government",)}, "Oficinas",
           labels={"government": "Administración pública"}),
    Sector("empleo", "Agencias de empleo y ETT", "Recruitment and staffing agencies", {"office": ("employment_agency",)}, "Oficinas",
           agency=True, mailboxes=("seleccion", "candidatos", "cv"), labels={"employment_agency": "Agencia de empleo / ETT"}),
    Sector("empresas", "Oficinas de empresas (cualquier sector)", "Company offices (any sector)", {"office": ("company",)}, "Oficinas",
           labels={"company": "Empresa"}),
    # --- salud y cuidados
    Sector("salud", "Clínicas y hospitales", "Clinics and hospitals",
           {"amenity": ("clinic", "hospital", "doctors", "dentist"), "healthcare": ("physiotherapist", "psychotherapist", "laboratory", "optometrist")},
           "Salud", mailboxes=("rrhh", "seleccion", "trabajaconnosotros"),
           labels={"clinic": "Clínica", "hospital": "Hospital", "doctors": "Consulta médica", "dentist": "Dentista", "physiotherapist": "Fisioterapia",
                   "psychotherapist": "Psicología", "laboratory": "Laboratorio", "optometrist": "Óptica"}),
    Sector("farmacia", "Farmacias", "Pharmacies", {"amenity": ("pharmacy",)}, "Salud", labels={"pharmacy": "Farmacia"}),
    Sector("veterinaria", "Veterinaria", "Veterinary", {"amenity": ("veterinary",)}, "Salud", labels={"veterinary": "Veterinaria"}),
    Sector("cuidados", "Residencias y cuidado de mayores", "Care homes", {"amenity": ("nursing_home", "social_facility")}, "Salud",
           labels={"nursing_home": "Residencia", "social_facility": "Servicios sociales"}),
    # --- educación
    Sector("educacion", "Colegios y academias", "Schools and academies",
           {"amenity": ("school", "language_school", "music_school", "driving_school", "kindergarten")}, "Educación",
           labels={"school": "Colegio", "language_school": "Academia de idiomas", "music_school": "Escuela de música",
                   "driving_school": "Autoescuela", "kindergarten": "Escuela infantil"}),
    Sector("universidad", "Universidades y centros de FP", "Universities and colleges", {"amenity": ("university", "college")}, "Educación",
           mailboxes=("phd", "research", "empleo"), labels={"university": "Universidad", "college": "Centro de FP / college"}),
    # --- hostelería, turismo y ocio
    Sector("hoteles", "Hoteles y alojamientos", "Hotels and accommodation",
           {"tourism": ("hotel", "hostel", "guest_house", "apartment", "camp_site")}, "Hostelería y turismo",
           mailboxes=("rrhh", "empleo", "jobs", "reservas"),
           labels={"hotel": "Hotel", "hostel": "Albergue", "guest_house": "Casa de huéspedes", "apartment": "Apartamentos turísticos", "camp_site": "Camping"}),
    Sector("restauracion", "Restaurantes, cafeterías y bares", "Restaurants, cafés and bars",
           {"amenity": ("restaurant", "cafe", "bar", "pub", "fast_food")}, "Hostelería y turismo",
           labels={"restaurant": "Restaurante", "cafe": "Cafetería", "bar": "Bar", "pub": "Pub", "fast_food": "Comida rápida"}),
    Sector("turismo", "Agencias de viajes y turismo", "Travel agencies and tourism",
           {"shop": ("travel_agency",), "office": ("travel_agent",), "tourism": ("museum", "theme_park", "attraction")}, "Hostelería y turismo",
           labels={"travel_agency": "Agencia de viajes", "travel_agent": "Agencia de viajes", "museum": "Museo",
                   "theme_park": "Parque temático", "attraction": "Atracción turística"}),
    Sector("deporte", "Gimnasios y centros deportivos", "Gyms and sports centres",
           {"leisure": ("fitness_centre", "sports_centre", "golf_course", "marina")}, "Hostelería y turismo",
           labels={"fitness_centre": "Gimnasio", "sports_centre": "Centro deportivo", "golf_course": "Golf", "marina": "Puerto deportivo"}),
    # --- comercio
    Sector("comercio", "Tiendas y comercio", "Shops and retail",
           {"shop": ("supermarket", "department_store", "clothes", "shoes", "electronics", "furniture", "hardware", "books", "sports", "toys")},
           "Comercio", labels={"supermarket": "Supermercado", "department_store": "Grandes almacenes", "clothes": "Moda", "shoes": "Calzado",
                               "electronics": "Electrónica", "furniture": "Muebles", "hardware": "Ferretería", "books": "Librería",
                               "sports": "Deportes", "toys": "Juguetes"}),
    Sector("belleza", "Peluquerías y estética", "Hair and beauty", {"shop": ("hairdresser", "beauty", "cosmetics")}, "Comercio",
           labels={"hairdresser": "Peluquería", "beauty": "Estética", "cosmetics": "Cosmética"}),
    Sector("automocion", "Automoción y talleres", "Automotive and garages", {"shop": ("car", "car_repair", "car_parts", "motorcycle")},
           "Comercio", labels={"car": "Concesionario", "car_repair": "Taller", "car_parts": "Recambios", "motorcycle": "Motos"}),
    # --- industria y oficios
    Sector("industria", "Fábricas e industria", "Factories and industry", {"man_made": ("works",), "landuse": ("industrial",)},
           "Industria y oficios", labels={"works": "Fábrica", "industrial": "Polígono / industria"}),
    Sector("oficios", "Oficios e instalaciones", "Trades and installers",
           {"craft": ("electrician", "plumber", "carpenter", "hvac", "painter", "roofer", "metal_construction", "joiner")},
           "Industria y oficios", labels={"electrician": "Electricidad", "plumber": "Fontanería", "carpenter": "Carpintería",
                                          "hvac": "Climatización", "painter": "Pintura", "roofer": "Tejados",
                                          "metal_construction": "Metalistería", "joiner": "Ebanistería"}),
    Sector("alimentacion", "Alimentación y bebidas (producción)", "Food and drink production",
           {"craft": ("bakery", "brewery", "winery", "confectionery", "distillery"), "shop": ("bakery",)}, "Industria y oficios",
           labels={"bakery": "Panadería / obrador", "brewery": "Cervecera", "winery": "Bodega", "confectionery": "Confitería", "distillery": "Destilería"}),
    Sector("maritimo", "Sector marítimo y portuario", "Maritime and port", {"office": ("shipping_agent",), "industrial": ("port", "shipyard")},
           "Industria y oficios", mailboxes=("crewing", "crew", "cadets"),
           labels={"shipping_agent": "Agente marítimo", "port": "Puerto", "shipyard": "Astillero"}),
    Sector("agricultura", "Agricultura y medio ambiente", "Agriculture and environment",
           {"office": ("agricultural_consultancy", "forestry", "water_utility"), "landuse": ("farmyard",)}, "Industria y oficios",
           labels={"agricultural_consultancy": "Consultoría agraria", "forestry": "Forestal", "water_utility": "Agua", "farmyard": "Explotación agraria"}),
]

BY_ID: dict[str, Sector] = {s.id: s for s in SECTORS}


def catalog() -> list[dict]:
    return [{"id": s.id, "label": {"es": s.es, "en": s.en}, "group": s.group, "agency": s.agency,
             "osm": {k: list(v) for k, v in s.osm.items()}} for s in SECTORS]
