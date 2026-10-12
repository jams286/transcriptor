# transcriptor (personal)

Tool solo para Jams: pega una URL de video, elige formato e idioma, y obtiene el archivo y (opcional) su transcripción.

## Permiso especial: disco JamsData

**Este proyecto SÍ puede escribir en `/media/datos/transcriptor/`** (y solo ahí), autorizado por Jams el 2026-10-11.
Fuera de esa carpeta sigue aplicando la regla global: no tocar nada más de `/media/datos`.

## Requisitos acordados

- Formatos: MP3 (por defecto) o MP4 con calidad: mejor / 1080p / 720p / 480p (limita el lado corto, para que los verticales salgan bien).
- Compatibilidad del MP4: "compatible" (por defecto, H.264+AAC, hasta 1080p en YouTube, se ve en cualquier iPhone) o "maxima" (AV1/VP9, hasta 4K; iPhone anteriores al 15 Pro lo ven negro). Si en modo compatible el sitio no da H.264+AAC, `motor.hacer_compatible` lo convierte con ffmpeg (estado `recodificando`, barra "Conversión").
- Transcripción solo disponible con MP3 (casilla deshabilitada con MP4). Salida .txt.
- Idioma: automático o elegido de una lista.
- Modelo: "rápido" = `small` (por defecto), "preciso" = `medium`. Motor: faster-whisper (CPU, int8).
- Barras de progreso: descarga (y conversión) y, si aplica, transcripción. Los botones de descarga aparecen solo al terminar todo.
- Historial de trabajos, con opción de borrar (Jams lo limpia a mano).
- Descargas desde el celular o la PC dentro de la red.
- Solo red local (el server no está expuesto); el backend escucha solo en 127.0.0.1.
- Interfaz en español, mobile-first, colores claros. Usar la skill `frontend-design` (en `.claude/skills/`, copia del repo oficial anthropics/skills).

## Arquitectura

- Backend Python (stdlib + yt-dlp + faster-whisper) en `.venv/`, cola de un trabajo a la vez, en 127.0.0.1:8765.
- nginx: `/transcriptor/` → estático en `/var/www/transcriptor/`; `/transcriptor/api/` → proxy al backend (config en `~/proyectos/infra/nginx`).
- Servicio systemd de usuario (sin sudo para reiniciar).
- Datos y archivos en `/media/datos/transcriptor/`.

## Archivos

- `motor.py`: descarga (yt-dlp) y transcripción (faster-whisper). Se puede probar suelto: `.venv/bin/python motor.py <URL> mp3 --transcribir --idioma es` (deja todo en `/media/datos/transcriptor/pruebas/`).
- `servidor.py`: API + cola. Trabajos en `/media/datos/transcriptor/trabajos/<id>/` (`trabajo.json` + archivos).
  - `GET /api/trabajos`, `POST /api/trabajos`, `GET /api/trabajos/<id>`, `DELETE /api/trabajos/<id>`, `GET /api/trabajos/<id>/archivo/<nombre>`.
- `web/`: página estática (sondea la API cada 1 s si hay trabajos activos, si no cada 15 s).
- `servicio/transcriptor.service`: unidad systemd de usuario.
- `cookies.txt` (opcional, fuera de git): si existe, yt-dlp lo usa (Instagram/X).

## Publicar y operar

- Página: `rsync -a --delete ~/proyectos/personal/transcriptor/web/ /var/www/transcriptor/`
- Servicio: `systemctl --user restart transcriptor` / `journalctl --user -u transcriptor -f`
- Instalar dependencias: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt` (`av` va fijo, ver comentario en requirements.txt).
- Actualizar yt-dlp cuando un sitio deje de funcionar: `.venv/bin/pip install -U yt-dlp` y reiniciar el servicio.
- Ojo: el sistema trae un `yt_dlp` viejo (2024) en `/usr/lib/python3/dist-packages`; usar siempre el de `.venv/`.

## Diseño

Plan (skill frontend-design): fondo gris azulado claro `#e9eff3`, tinta pizarra `#17262f`, verde azulado `#0d7a80` = descarga, índigo `#4a4fc4` = transcripción. Letra Atkinson Hyperlegible (Google Fonts) con respaldo del sistema. Una columna alineada a la izquierda. Elemento distintivo: la barra de transcripción se llena con "renglones" (trazos como palabras). El trabajo activo va en superficie blanca; el historial es una lista simple, sin tarjetas con sombra.
