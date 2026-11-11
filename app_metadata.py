"""Metadatos visibles de la aplicación y de la versión desplegada."""

APP_NAME = "Piña Transcribe"
APP_VERSION = "3.0.0"
UPDATED_AT = "2026-11-11"
APP_REPO = "https://github.com/webcvalejandropina-ui/pina-transcribe"

# Cambios de la versión, en los dos idiomas de la interfaz.
APP_CHANGES = {
    "es": (
        "Modo claro, oscuro y automático con el mismo diseño editorial.",
        "Interfaz completa en español e inglés.",
        "Recorte por inicio y fin: solo se descarga el tramo elegido.",
        "Subtítulos .srt además del .txt.",
        "El modelo queda cargado entre trabajos y usa todos los núcleos.",
        "Recomendación de modelo según la CPU, la RAM y la GPU de tu equipo.",
    ),
    "en": (
        "Light, dark and automatic themes on the same editorial design.",
        "Full interface in Spanish and English.",
        "Start/end trimming: only the selected range is downloaded.",
        ".srt subtitles alongside the .txt file.",
        "The model stays loaded between jobs and uses every CPU core.",
        "Model recommendation based on your CPU, RAM and GPU.",
    ),
}
