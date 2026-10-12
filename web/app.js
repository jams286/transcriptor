// Transcriptor: formulario + historial con progreso (sondea la API mientras haya trabajos activos)
(() => {
  'use strict';

  const API = 'api/trabajos';
  const ACTIVOS = ['en_cola', 'descargando', 'convirtiendo', 'transcribiendo'];
  const IDIOMAS = {
    es: 'español', en: 'inglés', pt: 'portugués', fr: 'francés', de: 'alemán', it: 'italiano',
    ja: 'japonés', ko: 'coreano', zh: 'chino', ru: 'ruso', ar: 'árabe', hi: 'hindi',
  };

  const $ = sel => document.querySelector(sel);
  const form = $('#formulario');
  const urlInput = $('#url');
  const grupoCalidad = $('#grupo-calidad');
  const grupoCompatibilidad = $('#grupo-compatibilidad');
  const transcribir = $('#transcribir');
  const notaMp4 = $('#nota-mp4');
  const opcionesTexto = $('#opciones-texto');
  const aviso = $('#aviso');
  const enviar = $('#enviar');
  const lista = $('#trabajos');
  const vacio = $('#vacio');

  const confirmando = new Set();   // ids con el botón "borrar" esperando el segundo toque
  let temporizador = null;

  // ---------- Formulario ----------
  function formato() { return form.formato.value; }

  function ajustarFormulario() {
    const esVideo = formato() === 'mp4';
    grupoCalidad.hidden = !esVideo;
    grupoCompatibilidad.hidden = !esVideo;
    transcribir.disabled = esVideo;
    if (esVideo) transcribir.checked = false;
    notaMp4.hidden = !esVideo;
    opcionesTexto.hidden = !transcribir.checked;
    enviar.textContent = esVideo ? 'Descargar video'
      : transcribir.checked ? 'Descargar y transcribir' : 'Descargar audio';
  }

  function mostrarAviso(texto) {
    aviso.textContent = texto || '';
    aviso.hidden = !texto;
  }

  form.addEventListener('change', ajustarFormulario);

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const url = urlInput.value.trim();
    if (!/^https?:\/\/\S+$/i.test(url)) {
      mostrarAviso('Pega el enlace completo del video, empezando con https://');
      urlInput.focus();
      return;
    }
    mostrarAviso('');
    enviar.disabled = true;
    try {
      const resp = await fetch(API, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url,
          formato: formato(),
          calidad: form.calidad.value,
          compatibilidad: form.compatibilidad.value,
          transcribir: transcribir.checked,
          idioma: form.idioma.value,
          modelo: form.modelo.value,
        }),
      });
      const datos = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(datos.error || `El servicio respondió ${resp.status}.`);
      urlInput.value = '';
      await cargar();
      lista.firstElementChild?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    } catch (err) {
      mostrarAviso(err.message === 'Failed to fetch'
        ? 'No hay conexión con el servicio del transcriptor. Revisa que el server esté encendido.'
        : err.message);
    } finally {
      enviar.disabled = false;
    }
  });

  // ---------- Historial ----------
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

  function fecha(iso) {
    const d = new Date(iso);
    const hora = d.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit' });
    const hoy = new Date().toDateString() === d.toDateString();
    return hoy ? `hoy, ${hora}` : `${d.toLocaleDateString('es', { day: 'numeric', month: 'short' })}, ${hora}`;
  }

  function detalle(t) {
    const partes = [];
    if (t.formato === 'mp4') {
      partes.push(t.calidad === 'mejor' ? 'Video MP4 en la mejor calidad' : `Video MP4 en ${t.calidad}p`);
      if (t.compatibilidad) {
        partes.push(t.compatibilidad === 'maxima' ? 'para equipos recientes' : 'para cualquier celular o PC');
      }
    } else if (t.transcribir) {
      const idioma = t.idioma ? IDIOMAS[t.idioma] : 'idioma automático';
      partes.push(`Audio MP3 con transcripción ${t.modelo === 'preciso' ? 'precisa' : 'rápida'} (${idioma})`);
    } else {
      partes.push('Audio MP3');
    }
    partes.push(fecha(t.creado));
    return partes.join(', ');
  }

  function textoEstado(t) {
    switch (t.estado) {
      case 'en_cola': return 'En espera: empieza cuando termine la descarga anterior.';
      case 'descargando': return 'Descargando…';
      case 'convirtiendo': return t.formato === 'mp3' ? 'Convirtiendo a MP3…' : 'Uniendo video y audio…';
      case 'transcribiendo': return 'Transcribiendo…';
      case 'listo':
        return t.transcribir && t.idioma_detectado
          ? `Listo. Transcrito en ${IDIOMAS[t.idioma_detectado] || t.idioma_detectado}.` : 'Listo.';
      default: return t.error || 'Falló.';
    }
  }

  function barra(tipo, nombre, pct, extra = '') {
    const valor = Math.round(pct || 0);
    return `
      <div class="barra ${tipo} ${extra}" role="progressbar" aria-label="${nombre}"
           aria-valuemin="0" aria-valuemax="100" ${extra.includes('indefinida') ? '' : `aria-valuenow="${valor}"`}>
        <span class="barra-nombre">${nombre}</span>
        <div class="barra-pista"><div class="barra-relleno" style="width:${valor}%"></div></div>
        <span class="barra-numero">${extra.includes('indefinida') ? '' : valor + '%'}</span>
      </div>`;
  }

  function etiquetaArchivo(nombre) {
    const ext = nombre.split('.').pop().toLowerCase();
    if (ext === 'txt') return ['Bajar texto (.txt)', 'txt'];
    if (ext === 'mp4') return ['Bajar video', ''];
    return ['Bajar audio', ''];
  }

  function htmlTrabajo(t) {
    const activo = ACTIVOS.includes(t.estado);
    let barras = '';
    if (activo) {
      const convirtiendo = t.estado === 'convirtiendo';
      barras += barra('descarga', t.formato === 'mp4' ? 'Video' : 'Audio',
        t.progreso_descarga, convirtiendo ? 'indefinida' : '');
      if (t.transcribir) {
        barras += barra('texto', 'Transcripción', t.progreso_transcripcion,
          t.estado === 'transcribiendo' ? '' : 'espera');
      }
    }

    let acciones = '';
    if (t.estado === 'listo') {
      acciones += t.archivos.map(nombre => {
        const [texto, clase] = etiquetaArchivo(nombre);
        const href = `${API}/${encodeURIComponent(t.id)}/archivo/${encodeURIComponent(nombre)}`;
        return `<a class="boton boton-bajar ${clase}" href="${href}" download>${texto}</a>`;
      }).join('');
    }
    if (!activo || t.estado === 'en_cola') {
      const conf = confirmando.has(t.id);
      acciones += `<button type="button" class="boton boton-borrar ${conf ? 'confirmar' : ''}" data-borrar="${esc(t.id)}">
        ${conf ? 'Toca otra vez para borrar' : 'Borrar'}</button>`;
    }

    return `
      <p class="trabajo-titulo">${esc(t.titulo || t.url)}</p>
      <p class="trabajo-detalle">${esc(detalle(t))}</p>
      <p class="estado ${t.estado === 'error' ? 'error' : ''}">${esc(textoEstado(t))}</p>
      ${barras}
      ${acciones ? `<div class="acciones">${acciones}</div>` : ''}`;
  }

  function pintar(trabajos) {
    vacio.hidden = trabajos.length > 0;
    const existentes = new Map([...lista.children].map(li => [li.dataset.id, li]));
    let anterior = null;
    for (const t of trabajos) {
      const firma = JSON.stringify([t.estado, t.titulo, Math.round(t.progreso_descarga),
        Math.round(t.progreso_transcripcion), t.archivos, t.error, confirmando.has(t.id)]);
      let li = existentes.get(t.id);
      existentes.delete(t.id);
      if (!li) {
        li = document.createElement('li');
        li.dataset.id = t.id;
      }
      if (li.dataset.firma !== firma) {
        li.className = 'trabajo' + (ACTIVOS.includes(t.estado) ? ' activo' : '');
        li.innerHTML = htmlTrabajo(t);
        li.dataset.firma = firma;
      }
      const lugar = anterior ? anterior.nextSibling : lista.firstChild;
      if (li !== lugar) lista.insertBefore(li, lugar);
      anterior = li;
    }
    existentes.forEach(li => li.remove());
  }

  let ultimos = [];

  async function cargar() {
    clearTimeout(temporizador);
    try {
      const resp = await fetch(API, { cache: 'no-store' });
      if (!resp.ok) throw new Error();
      ultimos = await resp.json();
      pintar(ultimos);
      if (aviso.dataset.conexion) { mostrarAviso(''); delete aviso.dataset.conexion; }
    } catch {
      mostrarAviso('No hay conexión con el servicio del transcriptor. Reintentando…');
      aviso.dataset.conexion = '1';
    }
    const hayActivos = ultimos.some(t => ACTIVOS.includes(t.estado));
    temporizador = setTimeout(cargar, hayActivos ? 1000 : 15000);
  }

  lista.addEventListener('click', async (e) => {
    const boton = e.target.closest('[data-borrar]');
    if (!boton) return;
    const id = boton.dataset.borrar;
    if (!confirmando.has(id)) {
      confirmando.add(id);
      pintar(ultimos);
      setTimeout(() => { if (confirmando.delete(id)) pintar(ultimos); }, 4000);
      return;
    }
    confirmando.delete(id);
    const resp = await fetch(`${API}/${encodeURIComponent(id)}`, { method: 'DELETE' }).catch(() => null);
    if (!resp || !resp.ok) {
      const datos = resp ? await resp.json().catch(() => ({})) : {};
      mostrarAviso(datos.error || 'No se pudo borrar. Intenta de nuevo.');
    }
    cargar();
  });

  document.addEventListener('visibilitychange', () => { if (!document.hidden) cargar(); });

  ajustarFormulario();
  cargar();
})();
