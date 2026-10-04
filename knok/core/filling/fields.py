"""Taxonomía de campos: claves canónicas que el motor sabe rellenar y de dónde sale cada valor.

source:
  profile   datos personales del perfil (nombre, email, teléfono…)
  answer    banco de respuestas del usuario (años de experiencia, salario, permiso de trabajo…)
  document  un archivo (CV, carta)
  template  texto generado con una plantilla (carta de presentación)
  consent   casillas de consentimiento: NUNCA se marcan solas
sensitive: datos especialmente protegidos (EEO, fecha de nacimiento…): solo se rellenan si el usuario
           guardó esa respuesta explícitamente; nunca se deducen.
"""
from dataclasses import dataclass, field

from knok.packs.schema import AnswerKey


@dataclass(frozen=True)
class FieldDef:
    key: str
    es: str
    en: str
    source: str
    type: str = "text"
    sensitive: bool = False
    options: tuple[str, ...] = field(default_factory=tuple)

    @property
    def labels(self) -> dict[str, str]:
        return {"es": self.es, "en": self.en}


FIELDS: list[FieldDef] = [
    # --- perfil
    FieldDef("first_name", "Nombre", "First name", "profile"),
    FieldDef("last_name", "Apellidos", "Last name", "profile"),
    FieldDef("full_name", "Nombre completo", "Full name", "profile"),
    FieldDef("email", "Email", "Email", "profile", "email"),
    FieldDef("phone", "Teléfono", "Phone", "profile", "tel"),
    FieldDef("city", "Ciudad", "City", "profile"),
    FieldDef("country", "País", "Country", "profile"),
    FieldDef("location", "Ubicación", "Location", "profile"),
    FieldDef("linkedin", "LinkedIn", "LinkedIn", "profile", "url"),
    FieldDef("github", "GitHub", "GitHub", "profile", "url"),
    FieldDef("website", "Web / portfolio", "Website / portfolio", "profile", "url"),
    # --- documentos y textos
    FieldDef("resume", "CV", "Resume / CV", "document", "file"),
    FieldDef("cover_letter_file", "Carta de presentación (archivo)", "Cover letter (file)", "document", "file"),
    FieldDef("cover_letter", "Carta de presentación", "Cover letter", "template", "textarea"),
    # --- banco de respuestas
    FieldDef("years_experience", "Años de experiencia", "Years of experience", "answer", "number"),
    FieldDef("salary_expectation", "Salario esperado", "Expected salary", "answer"),
    FieldDef("current_salary", "Salario actual", "Current salary", "answer"),
    FieldDef("notice_period", "Preaviso / incorporación", "Notice period", "answer"),
    FieldDef("start_date", "Fecha de incorporación", "Earliest start date", "answer", "date"),
    FieldDef("work_authorization", "Permiso de trabajo (países, p. ej. ES, EU)", "Work authorization (countries, e.g. ES, EU)", "answer"),
    FieldDef("needs_sponsorship", "¿Necesitas patrocinio de visado?", "Do you need visa sponsorship?", "answer", "boolean"),
    FieldDef("relocation", "¿Dispuesto a mudarte?", "Willing to relocate?", "answer", "boolean"),
    FieldDef("remote_preference", "Preferencia de modalidad", "Work arrangement preference", "answer", "choice",
             options=("remote", "hybrid", "onsite", "any")),
    FieldDef("willing_to_travel", "¿Disponibilidad para viajar?", "Willing to travel?", "answer", "boolean"),
    FieldDef("drivers_license", "¿Carné de conducir?", "Driver's license?", "answer", "boolean"),
    FieldDef("current_company", "Empresa actual", "Current company", "answer"),
    FieldDef("current_title", "Puesto actual", "Current title", "answer"),
    FieldDef("highest_education", "Nivel de estudios", "Highest education", "answer", "choice",
             options=("secondary", "vocational", "bachelor", "master", "phd")),
    FieldDef("degree", "Titulación", "Degree", "answer"),
    FieldDef("university", "Universidad / centro", "University / school", "answer"),
    FieldDef("graduation_year", "Año de graduación", "Graduation year", "answer", "number"),
    FieldDef("languages_summary", "Idiomas (texto libre)", "Languages (free text)", "answer"),
    FieldDef("nationality", "Nacionalidad", "Nationality", "answer"),
    FieldDef("how_did_you_hear", "¿Cómo nos conociste?", "How did you hear about us?", "answer"),
    FieldDef("pronouns", "Pronombres", "Pronouns", "answer"),
    FieldDef("references", "Referencias", "References", "answer", "textarea"),
    # --- sensibles: solo si el usuario los guardó explícitamente
    FieldDef("date_of_birth", "Fecha de nacimiento", "Date of birth", "answer", "date", sensitive=True),
    FieldDef("eeo_gender", "Género (EEO)", "Gender (EEO)", "answer", sensitive=True),
    FieldDef("eeo_ethnicity", "Origen étnico (EEO)", "Race / ethnicity (EEO)", "answer", sensitive=True),
    FieldDef("eeo_veteran", "Veterano (EEO)", "Veteran status (EEO)", "answer", sensitive=True),
    FieldDef("eeo_disability", "Discapacidad (EEO)", "Disability status (EEO)", "answer", sensitive=True),
    # --- consentimientos
    FieldDef("consent", "Consentimiento / condiciones", "Consent / terms", "consent", "boolean"),
]

BY_KEY: dict[str, FieldDef] = {f.key: f for f in FIELDS}

GLOBAL_ANSWER_KEYS: list[AnswerKey] = [
    AnswerKey(key=f.key, label=f.labels, type=f.type if f.type != "date" else "text", options=list(f.options))
    for f in FIELDS if f.source == "answer"
]


def is_sensitive(key: str) -> bool:
    f = BY_KEY.get(key)
    return bool(f and f.sensitive)
