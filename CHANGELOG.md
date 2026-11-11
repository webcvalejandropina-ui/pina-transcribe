# Changelog

## 3.0.0 - 2026-11-11

**Español**

- Modo claro, oscuro o automático sobre el diseño editorial de siempre (líneas rectas, tipografía condensada).
- Interfaz completa en español e inglés (detecta el idioma del navegador y se puede cambiar).
- Recorte por inicio y fin (`start`/`end` en la API, `--start`/`--end` en la CLI): solo se descarga el tramo elegido.
- Subtítulos `.srt` con los tiempos del vídeo original, además del `.txt`.
- El modelo Whisper queda cargado entre trabajos y usa todos los hilos de CPU disponibles (`PINA_CPU_THREADS`, `PINA_KEEP_MODEL`).
- El audio se convierte a 16 kHz mono: archivos temporales ~6 veces más pequeños.
- Nueva tarjeta «Tu equipo» y endpoint `/api/system` con CPU, memoria, GPU y modelo recomendado.
- Procesador `auto` / `cpu` / `gpu` en la API (se mantiene `force_cpu` por compatibilidad).
- Errores con `code` estable para traducirlos en la interfaz.
- Interfaz servida como archivos estáticos con CSP estricta sin scripts en línea.
- Límite de memoria del contenedor configurable (`PINA_MEM_LIMIT`) y configuración en `pina.env`.
- Lanzador para Windows (`launch.cmd`); imagen CPU para `amd64` y `arm64`.
- Fija `av==18.1.0`: PyAV 19 rompe la lectura de audio de faster-whisper 1.2.1.
- El repositorio ya no incluye archivos ocultos.

**English**

- Light, dark or automatic themes on the same editorial design (straight lines, condensed type).
- Full interface in Spanish and English (follows the browser language and can be switched).
- Start/end trimming (`start`/`end` in the API, `--start`/`--end` in the CLI): only the selected range is downloaded.
- `.srt` subtitles timed to the original video, alongside the `.txt`.
- The Whisper model stays loaded between jobs and uses every available CPU thread (`PINA_CPU_THREADS`, `PINA_KEEP_MODEL`).
- Audio is converted to 16 kHz mono: temporary files are ~6x smaller.
- New "Your machine" card and `/api/system` endpoint with CPU, memory, GPU and recommended model.
- `auto` / `cpu` / `gpu` processor in the API (`force_cpu` kept for compatibility).
- Errors carry a stable `code` so the interface can translate them.
- Interface served as static files with a strict CSP and no inline scripts.
- Configurable container memory cap (`PINA_MEM_LIMIT`) and settings in `pina.env`.
- Windows launcher (`launch.cmd`); CPU image for `amd64` and `arm64`.
- Pins `av==18.1.0`: PyAV 19 breaks audio loading in faster-whisper 1.2.1.
- The repository no longer contains hidden files.

## 2.1.0 - 2026-09-16

- Actualiza y fija las dependencias directas, incluido `yt-dlp 2026.8.19`.
- Añade Deno y `yt-dlp-ejs` a las imágenes para resolver los retos JavaScript de YouTube.
- Prioriza audio HLS con fallback al mejor audio disponible y mejora los reintentos.
- Permite configurar cookies (`YTDLP_COOKIES_FILE`) o proxy (`YTDLP_PROXY`) sin incluir secretos en la imagen.
- Añade favicon propio, versión, fecha de actualización y resumen de cambios en la UI.
- Elimina Google Fonts para evitar solicitudes externas desde el navegador.
- Deshabilita Swagger, ReDoc y OpenAPI públicos; añade cabeceras HTTP de seguridad.
- Ejecuta las imágenes CPU y GPU sin root, con filesystem de solo lectura y capacidades eliminadas.
- Publica el puerto solo en `127.0.0.1` por defecto.
