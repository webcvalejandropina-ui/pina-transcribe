# Piña Transcribe

Transcriptor local para videos de **YouTube** y **Twitch VOD**. Descarga el audio con `yt-dlp`, lo normaliza con `ffmpeg` y genera una transcripción con `faster-whisper`, sin enviar el contenido a servicios externos.

**Versión actual:** `2.1.0` · **Actualizada:** `2026-09-16` · [Ver cambios](CHANGELOG.md)

Incluye una interfaz web en FastAPI, una CLI directa y un launcher interactivo para Docker.

## Características

- UI web en `http://127.0.0.1:15000` con progreso en vivo, historial reciente y descarga del `.txt`.
- Soporte para URLs completas o IDs de YouTube y Twitch.
- Modelos `faster-whisper` configurables (`tiny`, `base`, `small`, etc.).
- Ejecución local con Python o aislada con Docker.
- Perfil opcional para GPU NVIDIA mediante Docker Compose.
- Runtime Deno/EJS incluido para los retos JavaScript actuales de YouTube.
- Favicon, versión, fecha y cambios visibles en la interfaz.

## Requisitos

- Python 3.10 o superior para ejecución local.
- Docker y Docker Compose para la forma recomendada.
- `ffmpeg` en `PATH` si ejecutas sin Docker.
- Conexión a Internet para descargar el audio.

En Ubuntu puedes instalar `ffmpeg` con:

```bash
sudo apt update
sudo apt install -y ffmpeg
ffmpeg -version
```

## Arranque Rápido Con Docker

Levanta la interfaz web en segundo plano:

```bash
docker compose up -d --build transcribe
```

Abre la aplicación:

```text
http://127.0.0.1:15000
```

Por seguridad, Compose publica la aplicación únicamente en localhost. Para acceder desde otra máquina de una red confiable:

```bash
BIND_ADDRESS=0.0.0.0 docker compose up -d --build transcribe
```

No expongas el puerto `15000` directamente a Internet: la aplicación no implementa autenticación de usuarios.

También puedes usar el launcher incluido:

```bash
python3 launch_docker.py
```

Para ver logs o parar el servicio:

```bash
docker compose logs -f transcribe
docker compose stop transcribe
```

## Uso Local

Crea un entorno virtual e instala dependencias:

```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Ejecuta una transcripción:

```bash
python transcribe.py <youtube|twitch> VIDEO_ID [opciones]
```

Ejemplos:

```bash
python transcribe.py youtube dQw4w9WgXcQ
python transcribe.py twitch 1234567890 --model base --lang es
python transcribe.py youtube dQw4w9WgXcQ --cpu --no-color
```

Opciones principales:

- `--model NAME`: modelo de `faster-whisper`; por defecto `tiny`.
- `--lang LANG`: idioma fijo, por ejemplo `es`; si se omite, autodetecta.
- `--cpu`: fuerza CPU aunque haya GPU disponible.
- `--no-color`: desactiva colores ANSI en consola.

## API Web

La API procesa un trabajo a la vez para evitar saturar CPU/GPU.

- `GET /health`: comprueba que el servidor está vivo.
- `POST /api/jobs`: crea un trabajo de transcripción.
- `GET /api/jobs/{id}`: consulta estado, progreso y resultado.
- `GET /api/jobs/{id}/download`: descarga el `.txt` generado.

Ejemplo de payload:

```json
{
  "platform": "youtube",
  "video_id": "dQw4w9WgXcQ",
  "model": "tiny",
  "lang": "es",
  "force_cpu": true
}
```

## Docker

El servicio CPU usa la imagen local `pina-transcribe:cpu`:

```bash
docker compose up -d --build transcribe
```

El perfil GPU usa `pina-transcribe:gpu` y requiere NVIDIA Container Toolkit:

```bash
docker compose --profile gpu up -d --build transcribe-gpu
```

Comandos útiles dentro del contenedor:

```bash
docker compose run --rm -it transcribe launcher
docker compose run --rm transcribe youtube VIDEO_ID --cpu --model tiny
docker compose --profile gpu run --rm transcribe-gpu twitch 1234567890 --model base --lang es
```

Volúmenes montados:

- `outputs-data` -> `/app/outputs`
- `logs-data` -> `/app/logs`
- `model-cache` -> caché persistente de modelos Whisper.

La imagen CPU se ejecuta sin root. Compose activa filesystem de solo lectura, elimina capacidades Linux y añade un healthcheck.

## Configuración opcional de yt-dlp

La imagen ya incluye la versión compatible de `yt-dlp`, el paquete EJS y Deno. Si YouTube limita la IP del servidor, puedes usar cookies exportadas o un proxy sin añadirlos a la imagen:

```bash
cp .env.example .env
```

Variables disponibles:

- `YTDLP_PROXY`: URL de proxy compatible con yt-dlp.
- `YTDLP_COOKIES_FILE`: ruta interna a un archivo de cookies Netscape montado como volumen de solo lectura.

No subas cookies, tokens ni archivos `.env` al repositorio.

## Seguridad

- Swagger, ReDoc y OpenAPI están deshabilitados en producción.
- La UI no carga fuentes, analítica ni recursos de terceros.
- Se envían CSP, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy` y `Permissions-Policy`.
- Las URLs se reducen a un ID validado y luego se reconstruyen, evitando descargas arbitrarias.
- Los archivos descargables se validan para permanecer dentro de `outputs/`.
- La publicación de red queda limitada a `127.0.0.1` salvo configuración explícita.

## Salidas

- `outputs/<VIDEO_ID>.txt`: metadatos y transcripción final.
- `logs/transcribe.log`: registro de ejecución.
- `temp/`: archivos temporales eliminados al terminar cada trabajo.

Las carpetas `logs`, `temp` y `outputs` se crean automáticamente al ejecutar el proyecto.

## Estructura

```text
.
├── transcribe.py
├── web_server.py
├── docker_entrypoint.py
├── launcher.py
├── launch.sh
├── launch_docker.py
├── requirements.txt
├── Dockerfile
├── Dockerfile.gpu
├── docker-compose.yml
└── utils/
```

## Solución De Problemas

- `ffmpeg` no está instalado: instálalo en el sistema o usa Docker.
- ID inválido: YouTube usa IDs de 11 caracteres; Twitch VOD usa números.
- Video privado o no disponible: revisa la URL y los logs.
- GPU no detectada en Docker: usa el servicio CPU `transcribe`.
- Error de finales de línea en scripts: reconstruye con `docker compose build --no-cache transcribe`.
- `HTTP Error 403` de YouTube: reconstruye la imagen para obtener `yt-dlp`/EJS compatibles. Si la IP está limitada, configura `YTDLP_COOKIES_FILE` o `YTDLP_PROXY`.

## Licencia

Uso interno y educativo. Respeta los términos de YouTube y Twitch, además de las licencias de los modelos Whisper y de las dependencias usadas.
