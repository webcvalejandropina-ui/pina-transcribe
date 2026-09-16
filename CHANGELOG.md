# Changelog

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
