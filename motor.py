"""Descarga (yt-dlp) y transcripción (faster-whisper).

Se puede usar suelto para probar:
    .venv/bin/python motor.py <URL> [mp3|mp4] [--transcribir] [--idioma es]
"""

import os
from pathlib import Path

CALIDADES = {'mejor': None, '1080': 1080, '720': 720, '480': 480}
MODELOS = {'rapido': 'small', 'preciso': 'medium'}

_modelos_cargados = {}


def descargar(url, carpeta, formato='mp3', calidad='mejor', al_progresar=None):
    """Descarga `url` en `carpeta` y devuelve (titulo, ruta_del_archivo).

    al_progresar(fase, porcentaje) recibe fase 'descargando' (0-100) o
    'convirtiendo' (None: sin porcentaje, lo hace ffmpeg).
    """
    import yt_dlp

    avisar = al_progresar or (lambda fase, pct: None)
    vistos = []  # archivos que yt-dlp ya empezó (video y audio van por separado en MP4)

    def gancho_descarga(d):
        partes = len((d.get('info_dict') or {}).get('requested_formats') or []) or 1
        nombre = d.get('filename')
        if nombre not in vistos:
            vistos.append(nombre)
        indice = min(vistos.index(nombre), partes - 1)
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate')
            fraccion = (d.get('downloaded_bytes') or 0) / total if total else 0
            avisar('descargando', round((indice + min(fraccion, 1)) / partes * 100, 1))
        elif d['status'] == 'finished' and indice == partes - 1:
            avisar('convirtiendo', None)

    opciones = {
        'outtmpl': str(Path(carpeta) / '%(title).120B.%(ext)s'),
        'windowsfilenames': True,  # nombres que también sirvan al bajarlos en Windows
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'noprogress': True,
        'progress_hooks': [gancho_descarga],
    }
    cookies = Path(__file__).with_name('cookies.txt')
    if cookies.exists():
        opciones['cookiefile'] = str(cookies)

    if formato == 'mp3':
        opciones['format'] = 'bestaudio/best'
        opciones['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]
    else:
        alto = CALIDADES.get(calidad)
        limite = f'[height<={alto}]' if alto else ''
        # Preferir pistas que ya son MP4/M4A para no recodificar.
        opciones['format'] = (
            f'bestvideo{limite}[ext=mp4]+bestaudio[ext=m4a]/'
            f'bestvideo{limite}+bestaudio/best{limite}/best'
        )
        opciones['merge_output_format'] = 'mp4'

    with yt_dlp.YoutubeDL(opciones) as ydl:
        info = ydl.extract_info(url, download=True)
        ruta = info['requested_downloads'][0]['filepath']
    return info.get('title') or 'video', ruta


def transcribir(ruta_audio, ruta_txt, idioma=None, modelo='rapido', al_progresar=None):
    """Transcribe `ruta_audio` a `ruta_txt`. Devuelve el idioma usado.

    idioma=None detecta solo. al_progresar(porcentaje) va de 0 a 100.
    """
    from faster_whisper import WhisperModel

    nombre = MODELOS.get(modelo, 'small')
    if nombre not in _modelos_cargados:
        _modelos_cargados[nombre] = WhisperModel(
            nombre, device='cpu', compute_type='int8', cpu_threads=os.cpu_count() or 4)
    segmentos, info = _modelos_cargados[nombre].transcribe(ruta_audio, language=idioma or None)

    avisar = al_progresar or (lambda pct: None)
    avisar(0)
    with open(ruta_txt, 'w', encoding='utf-8') as f:
        for seg in segmentos:  # es un generador: transcribe mientras se recorre
            f.write(seg.text.strip() + '\n')
            if info.duration:
                avisar(round(min(seg.end / info.duration, 1) * 100, 1))
    avisar(100)
    return info.language


if __name__ == '__main__':
    import argparse

    p = argparse.ArgumentParser(description='Probar descarga y transcripción.')
    p.add_argument('url')
    p.add_argument('formato', nargs='?', default='mp3', choices=['mp3', 'mp4'])
    p.add_argument('--calidad', default='mejor', choices=list(CALIDADES))
    p.add_argument('--transcribir', action='store_true')
    p.add_argument('--idioma', default=None)
    p.add_argument('--modelo', default='rapido', choices=list(MODELOS))
    p.add_argument('--carpeta', default='/media/datos/transcriptor/pruebas')
    a = p.parse_args()

    Path(a.carpeta).mkdir(parents=True, exist_ok=True)
    titulo, ruta = descargar(a.url, a.carpeta, a.formato, a.calidad,
                             lambda fase, pct: print(f'\r{fase} {pct if pct is not None else ""}%   ', end='', flush=True))
    print(f'\nDescargado: {ruta}')
    if a.transcribir and a.formato == 'mp3':
        txt = str(Path(ruta).with_suffix('.txt'))
        lang = transcribir(ruta, txt, a.idioma, a.modelo,
                           lambda pct: print(f'\rtranscribiendo {pct}%   ', end='', flush=True))
        print(f'\nTranscripción ({lang}): {txt}')
