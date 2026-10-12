"""Servicio web del transcriptor: cola de trabajos + API JSON.

Escucha solo en 127.0.0.1; nginx publica /transcriptor/api/ -> /api/.
Cada trabajo vive en /media/datos/transcriptor/trabajos/<id>/ con su trabajo.json.

    .venv/bin/python servidor.py
"""

import json
import queue
import re
import secrets
import shutil
import threading
import time
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote

import motor

HOST, PUERTO = '127.0.0.1', 8765
RAIZ = Path('/media/datos/transcriptor/trabajos')

IDIOMAS = {'es', 'en', 'pt', 'fr', 'de', 'it', 'ja', 'ko', 'zh', 'ru', 'ar', 'hi'}

trabajos = {}            # id -> dict
candado = threading.Lock()
cola = queue.Queue()


# ---------- Persistencia ----------

def guardar(t):
    ruta = RAIZ / t['id'] / 'trabajo.json'
    tmp = ruta.with_suffix('.tmp')
    tmp.write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding='utf-8')
    tmp.replace(ruta)


def actualizar(t, **cambios):
    with candado:
        t.update(cambios)
        guardar(t)


def cargar_historial():
    RAIZ.mkdir(parents=True, exist_ok=True)
    for f in RAIZ.glob('*/trabajo.json'):
        try:
            t = json.loads(f.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if t['estado'] in ('descargando', 'convirtiendo', 'transcribiendo'):
            t.update(estado='error', error='Se interrumpió porque el servicio se reinició. Vuelve a pedirlo.')
            guardar(t)
        trabajos[t['id']] = t
    for t in sorted(trabajos.values(), key=lambda t: t['creado']):
        if t['estado'] == 'en_cola':
            cola.put(t['id'])


# ---------- Trabajador (uno a la vez) ----------

def procesar(t):
    carpeta = RAIZ / t['id']
    ultimo = {'pct': None, 'momento': 0}

    def progreso(campo, pct):
        # No reescribir el JSON en cada byte: solo si cambió el % entero o pasó 1 s.
        ahora = time.monotonic()
        if pct is not None and int(pct) == ultimo['pct'] and ahora - ultimo['momento'] < 1:
            with candado:
                t[campo] = pct
            return
        ultimo.update(pct=int(pct) if pct is not None else None, momento=ahora)
        actualizar(t, **{campo: pct})

    def al_descargar(fase, pct):
        if fase == 'convirtiendo':
            actualizar(t, estado='convirtiendo', progreso_descarga=100)
        else:
            if t['estado'] != 'descargando':
                actualizar(t, estado='descargando')
            progreso('progreso_descarga', pct)

    actualizar(t, estado='descargando', progreso_descarga=0)
    titulo, ruta = motor.descargar(t['url'], carpeta, t['formato'], t['calidad'], al_descargar)
    archivos = [Path(ruta).name]
    actualizar(t, titulo=titulo, progreso_descarga=100, archivos=list(archivos))

    if t['transcribir']:
        actualizar(t, estado='transcribiendo', progreso_transcripcion=0)
        txt = Path(ruta).with_suffix('.txt')
        idioma = motor.transcribir(ruta, txt, t['idioma'], t['modelo'],
                                   lambda pct: progreso('progreso_transcripcion', pct))
        archivos.append(txt.name)
        actualizar(t, idioma_detectado=idioma, progreso_transcripcion=100)

    actualizar(t, estado='listo', archivos=archivos, terminado=datetime.now().isoformat(timespec='seconds'))


def trabajador():
    while True:
        id_ = cola.get()
        t = trabajos.get(id_)
        if not t or t['estado'] != 'en_cola':
            continue  # lo borraron mientras esperaba
        try:
            procesar(t)
        except Exception as e:
            traceback.print_exc()
            actualizar(t, estado='error', error=mensaje_error(e))


def mensaje_error(e):
    texto = re.sub(r'\x1b\[[0-9;]*m', '', str(e)).replace('ERROR: ', '').strip()
    if 'login' in texto.lower() or 'cookies' in texto.lower():
        return 'El sitio pide iniciar sesión para este video. Hace falta un archivo de cookies.'
    if 'Unsupported URL' in texto:
        return 'Esa URL no es de un sitio compatible o no apunta a un video.'
    return texto[:400] or 'Falló sin mensaje.'


# ---------- API ----------

def nuevo_trabajo(datos):
    url = str(datos.get('url', '')).strip()
    if not re.match(r'^https?://', url):
        raise ValueError('Pega una URL completa, que empiece con http:// o https://.')
    formato = datos.get('formato', 'mp3')
    if formato not in ('mp3', 'mp4'):
        raise ValueError('Formato no válido.')
    calidad = datos.get('calidad', 'mejor')
    if calidad not in motor.CALIDADES:
        raise ValueError('Calidad no válida.')
    idioma = datos.get('idioma') or None
    if idioma == 'auto':
        idioma = None
    if idioma and idioma not in IDIOMAS:
        raise ValueError('Idioma no válido.')
    modelo = datos.get('modelo', 'rapido')
    if modelo not in motor.MODELOS:
        raise ValueError('Modelo no válido.')

    ahora = datetime.now()
    t = {
        'id': ahora.strftime('%Y%m%d-%H%M%S-') + secrets.token_hex(2),
        'creado': ahora.isoformat(timespec='seconds'),
        'url': url,
        'formato': formato,
        'calidad': calidad if formato == 'mp4' else None,
        'transcribir': bool(datos.get('transcribir')) and formato == 'mp3',
        'idioma': idioma,
        'modelo': modelo,
        'estado': 'en_cola',
        'titulo': None,
        'progreso_descarga': 0,
        'progreso_transcripcion': 0,
        'archivos': [],
        'error': None,
    }
    (RAIZ / t['id']).mkdir(parents=True)
    with candado:
        trabajos[t['id']] = t
        guardar(t)
    cola.put(t['id'])
    return t


class Manejador(BaseHTTPRequestHandler):
    server_version = 'transcriptor'

    def log_message(self, fmt, *args):
        pass  # sin ruido en journalctl por cada sondeo de progreso

    def responder(self, codigo, cuerpo):
        datos = json.dumps(cuerpo, ensure_ascii=False).encode('utf-8')
        self.send_response(codigo)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(datos)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(datos)

    def partes(self):
        return [unquote(p) for p in self.path.split('?')[0].strip('/').split('/')]

    def do_GET(self):
        p = self.partes()
        if p == ['api', 'trabajos']:
            with candado:
                lista = sorted((dict(t) for t in trabajos.values()), key=lambda t: t['creado'], reverse=True)
            return self.responder(200, lista)
        if len(p) == 3 and p[:2] == ['api', 'trabajos']:
            t = trabajos.get(p[2])
            return self.responder(200, t) if t else self.responder(404, {'error': 'No existe ese trabajo.'})
        if len(p) == 5 and p[:2] == ['api', 'trabajos'] and p[3] == 'archivo':
            return self.enviar_archivo(p[2], p[4])
        self.responder(404, {'error': 'Ruta no encontrada.'})

    def do_POST(self):
        if self.partes() != ['api', 'trabajos']:
            return self.responder(404, {'error': 'Ruta no encontrada.'})
        try:
            largo = int(self.headers.get('Content-Length') or 0)
            datos = json.loads(self.rfile.read(min(largo, 10_000)) or b'{}')
            t = nuevo_trabajo(datos)
        except ValueError as e:
            return self.responder(400, {'error': str(e)})
        self.responder(201, t)

    def do_DELETE(self):
        p = self.partes()
        if len(p) != 3 or p[:2] != ['api', 'trabajos']:
            return self.responder(404, {'error': 'Ruta no encontrada.'})
        with candado:
            t = trabajos.get(p[2])
            if not t:
                return self.responder(404, {'error': 'No existe ese trabajo.'})
            if t['estado'] in ('descargando', 'convirtiendo', 'transcribiendo'):
                return self.responder(409, {'error': 'Está en proceso. Espera a que termine para borrarlo.'})
            del trabajos[p[2]]
        shutil.rmtree(RAIZ / p[2], ignore_errors=True)
        self.responder(200, {'borrado': p[2]})

    def enviar_archivo(self, id_, nombre):
        t = trabajos.get(id_)
        if not t or nombre not in t['archivos']:
            return self.responder(404, {'error': 'No existe ese archivo.'})
        ruta = RAIZ / id_ / nombre
        if not ruta.is_file():
            return self.responder(404, {'error': 'El archivo ya no está en el disco.'})
        tipo = {'.mp3': 'audio/mpeg', '.mp4': 'video/mp4', '.txt': 'text/plain; charset=utf-8'}.get(
            ruta.suffix.lower(), 'application/octet-stream')
        self.send_response(200)
        self.send_header('Content-Type', tipo)
        self.send_header('Content-Length', str(ruta.stat().st_size))
        self.send_header('Content-Disposition', f"attachment; filename*=UTF-8''{quote(nombre)}")
        self.end_headers()
        with open(ruta, 'rb') as f:
            shutil.copyfileobj(f, self.wfile, 1024 * 1024)


if __name__ == '__main__':
    cargar_historial()
    threading.Thread(target=trabajador, daemon=True).start()
    print(f'transcriptor escuchando en http://{HOST}:{PUERTO}', flush=True)
    ThreadingHTTPServer((HOST, PUERTO), Manejador).serve_forever()
