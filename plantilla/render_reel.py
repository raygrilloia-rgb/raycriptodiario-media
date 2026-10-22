# Reel vertical (1080x1920, 30 fps) con la voz de Álvaro para @raycriptodiario.
# Cuenta la misma historia que el carrusel: una escena por slide, y cada escena dura lo que dura su locución.
# Idea sacada de 5chollos (plantilla/render_reel.mjs de ese proyecto): una locución por bloque para
# sincronizar texto y voz, pausas recortadas para dar ritmo y música que baja sola cuando habla la voz.
# Se ejecuta en COMPOSIO_REMOTE_WORKBENCH DESPUÉS de render_slides.py (usa sus fuentes, colores y utilidades).
#
# Uso (cada paso en su propia celda, porque cada celda tiene un límite de 180 s):
#   exec(open('/mnt/files/plantilla/render_slides.py').read())
#   exec(open('/mnt/files/plantilla/render_reel.py').read())
#   info = preparar_reel(spec)     # voces, música y tiempos; devuelve la duración y las escenas
#   renderizar_reel(150)           # repetir en celdas nuevas hasta que devuelva True
#   mp4 = codificar_reel()
#   ref = subir_video(mp4)         # {name, mimetype: "video/mp4", s3key} para video_file
#
# spec: el mismo del carrusel. Solo entran en el reel las slides con campo "voz" (lo que dice Álvaro, máx. 10 palabras):
#   lo normal son 5 (portada, qué pasó, dato, qué significa para ti y cierre), para un reel de 15-20 s.
#   La portada se ve desde el primer fotograma y la voz la acompaña con subtítulos palabra a palabra.
#   Opcionales: "imagen_reel" en una slide (ilustración vertical que sustituye a "imagen"),
#               spec["voz_reel"] = {"nombre": "es-ES-AlvaroNeural", "rate": "+20%", "pitch": "+2Hz"},
#               spec["musica"] = False para quitar la base musical (por defecto va, generada por código y sin derechos).
# Una slide noticia sin imagen reutiliza la ilustración de la portada.

import asyncio, io, math, re, shutil, subprocess, sys, time, wave
import numpy as np
from concurrent.futures import ThreadPoolExecutor

RW, RH, FPS = 1080, 1920, 30
REEL_DIR = '/tmp/reel'
RTXT = RW - M - 150        # ancho del texto: a la derecha van los botones de Instagram
IMG_H = 1150               # alto de la zona de la ilustración
VOZ_REEL = {'nombre': 'es-ES-AlvaroNeural', 'rate': '+20%', 'pitch': '+2Hz'}
CLARO = (226, 232, 242)
_R = {}


def _pip(mod, pkg=None):
    try:
        return __import__(mod)
    except ImportError:
        subprocess.run([sys.executable, '-m', 'pip', 'install', '-q', pkg or mod], capture_output=True)
        return __import__(mod)


def _ff():
    return _pip('imageio_ffmpeg', 'imageio-ffmpeg').get_ffmpeg_exe()


def _dur(f):
    r = subprocess.run([_ff(), '-hide_banner', '-i', f], capture_output=True, text=True)
    m = re.search(r'Duration: (\d+):(\d+):([\d.]+)', r.stderr)
    return int(m[1]) * 3600 + int(m[2]) * 60 + float(m[3]) if m else 0.0


# ---------- voz ----------
def _tts(texto, mp3, voz):
    # Devuelve [(inicio_s, fin_s, palabra)] con el momento de cada palabra, para los subtítulos.
    edge_tts = _pip('edge_tts', 'edge-tts')
    palabras = []

    async def go():
        try:
            c = edge_tts.Communicate(texto, voz['nombre'], rate=voz['rate'], pitch=voz['pitch'], boundary='WordBoundary')
        except TypeError:  # versiones antiguas: siempre dan WordBoundary
            c = edge_tts.Communicate(texto, voz['nombre'], rate=voz['rate'], pitch=voz['pitch'])
        with open(mp3, 'wb') as f:
            async for ch in c.stream():
                if ch['type'] == 'audio':
                    f.write(ch['data'])
                elif ch['type'] == 'WordBoundary':
                    ini = ch['offset'] / 1e7
                    palabras.append((ini, ini + ch['duration'] / 1e7, ch['text']))
    asyncio.run(go())  # se llama desde un hilo, así no choca con el bucle de Jupyter
    return palabras


def _palabras_repartidas(texto, dur):
    # Si Edge no da los tiempos de cada palabra, se reparten según su longitud.
    ps = texto.split()
    total = sum(len(p) + 2 for p in ps) or 1
    t, out = 0.0, []
    for p in ps:
        d = dur * (len(p) + 2) / total
        out.append((t, t + d, p))
        t += d
    return out


def _locucion(i, texto, voz):
    mp3, wav = f'{REEL_DIR}/voz{i}.mp3', f'{REEL_DIR}/voz{i}.wav'
    err = None
    for _ in range(2):
        try:
            palabras = _tts(texto, mp3, voz)
            err = None
            break
        except Exception as e:
            err = e
            time.sleep(2)
    if err:
        raise err
    # Edge devuelve las palabras sin signos ("Sabías" en vez de "¿Sabías"): si cuadran, se usa el texto original.
    originales = texto.split()
    if len(originales) == len(palabras):
        palabras = [(a, b, o) for (a, b, _), o in zip(palabras, originales)]
    # Solo se recorta el silencio del final: si se recortaran las pausas de dentro,
    # los tiempos de las palabras dejarían de coincidir con los subtítulos.
    subprocess.run([_ff(), '-y', '-hide_banner', '-loglevel', 'error', '-i', mp3, '-af',
                    'areverse,silenceremove=start_periods=1:start_threshold=-42dB:start_silence=0.12,areverse,aresample=48000',
                    '-ac', '1', wav], check=True)
    return wav, palabras


# ---------- música: base tranquila generada por código (sin derechos de autor) ----------
def _musica(seg, ruta, bpm=96):
    sr = 48000
    n = int((seg + 1) * sr)
    out = np.zeros(n)
    beat = 60 / bpm
    acorde = beat * 8  # dos compases por acorde
    prog = [(220.0, 261.63, 329.63), (174.61, 220.0, 261.63), (130.81, 196.0, 261.63), (196.0, 246.94, 293.66)]

    def suma(i0, onda):
        i1 = min(n, i0 + len(onda))
        if i1 > i0:
            out[i0:i1] += onda[:i1 - i0]

    for k in range(int(seg / acorde) + 2):
        notas = prog[k % 4]
        tt = np.arange(int((acorde + 1.5) * sr)) / sr
        env = np.minimum(1, tt / 0.8) * np.exp(-np.maximum(0, tt - acorde) * 3)
        pad = sum(np.sin(2 * np.pi * f * d * h * tt) / h ** 2 for f in notas for d in (0.998, 1.002) for h in (1, 2, 3))
        bajo = np.sin(2 * np.pi * notas[0] / 2 * tt) * 1.2
        suma(int(k * acorde * sr), (pad * 0.12 + bajo * 0.35) * env)
        # arpegio en corcheas
        for j in range(16):
            ta = np.arange(int(beat / 2 * sr * 1.5)) / sr
            f = notas[j % 3] * (2 if j % 6 < 3 else 4)
            suma(int((k * acorde + j * beat / 2) * sr), np.sin(2 * np.pi * f * ta) * np.exp(-ta * 7) * 0.10)
    for b in range(int(seg / beat) + 2):
        tk = np.arange(int(0.3 * sr)) / sr
        if b % 2 == 0:  # bombo suave en 1 y 3
            fase = 2 * np.pi * (50 * tk + 70 / 30 * (1 - np.exp(-30 * tk)))
            suma(int(b * beat * sr), np.sin(fase) * np.exp(-tk * 9) * 0.45)
        th = np.arange(int(0.05 * sr)) / sr  # charles en el contratiempo
        suma(int((b + 0.5) * beat * sr), np.random.uniform(-1, 1, len(th)) * np.exp(-th * 70) * 0.05)
    out = out[:int(seg * sr)]
    out /= max(1e-9, np.abs(out).max()) * 1.15
    fade = int(1.2 * sr)
    out[:int(0.4 * sr)] *= np.linspace(0, 1, int(0.4 * sr))
    out[-fade:] *= np.linspace(1, 0, fade)
    with wave.open(ruta, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((out * 32000).astype(np.int16).tobytes())
    return ruta


def _mezcla(escenas, total, con_musica):
    ff, voz, salida = _ff(), f'{REEL_DIR}/voz.wav', f'{REEL_DIR}/audio.wav'
    hablan = [e for e in escenas if e.get('wav')]
    if hablan:
        ins, fil = [], []
        for i, e in enumerate(hablan):
            ins += ['-i', e['wav']]
            ms = round(e['voz_ini'] * 1000)
            fil.append(f'[{i}:a]adelay={ms}|{ms}[v{i}]')
        filtro = ';'.join(fil) + ';' + ''.join(f'[v{i}]' for i in range(len(hablan))) \
            + f'amix=inputs={len(hablan)}:normalize=0,apad,atrim=0:{total:.2f}[v]'
        subprocess.run([ff, '-y', '-hide_banner', '-loglevel', 'error', *ins, '-filter_complex', filtro,
                        '-map', '[v]', '-ac', '1', '-ar', '48000', voz], check=True)
    if con_musica:
        mus = _musica(total, f'{REEL_DIR}/musica.wav')
    if hablan and con_musica:
        filtro = ('[0:a]volume=0.30[m];[1:a]volume=1.5,asplit[va][vb];'
                  '[m][va]sidechaincompress=threshold=0.03:ratio=8:attack=15:release=350[md];'
                  '[md][vb]amix=inputs=2:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=9[a]')
        args = ['-i', mus, '-i', voz, '-filter_complex', filtro, '-map', '[a]']
    elif hablan or con_musica:
        args = ['-i', voz if hablan else mus, '-af', 'loudnorm=I=-14:TP=-1.5:LRA=9']
    else:
        args = ['-f', 'lavfi', '-i', 'anullsrc=r=48000:cl=mono', '-t', f'{total:.2f}']
    subprocess.run([ff, '-y', '-hide_banner', '-loglevel', 'error', *args, '-ar', '48000', '-ac', '2', salida], check=True)
    return salida


# ---------- capas de texto ----------
def _ease(k):
    return 1 - (1 - k) ** 3


def _back(k):
    c1 = 1.70158
    return 1 + (c1 + 1) * (k - 1) ** 3 + c1 * (k - 1) ** 2


def _capa_texto(texto, familia, peso, size, ancho, max_l, min_size, color, inter=1.1, centro=False):
    tmp = ImageDraw.Draw(Image.new('RGB', (10, 10)))
    f, lineas = _bloque(tmp, texto, familia, peso, size, ancho, max_l, min_size)
    alto = round(f.size * inter)
    im = Image.new('RGBA', (ancho, alto * len(lineas) + round(f.size * 0.3)), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for j, l in enumerate(lineas):
        if centro:
            d.text((ancho // 2, j * alto), l, font=f, fill=color, anchor='ma')
        else:
            d.text((0, j * alto), l, font=f, fill=color)
    return im


def _capa_chip(texto, color):
    im = Image.new('RGBA', (RW, 60), (0, 0, 0, 0))
    _chip(ImageDraw.Draw(im), (0, 0), texto, color)
    return im.crop(im.getbbox())


def _cabecera_reel(fecha, color):
    im = Image.new('RGBA', (RW, 50), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((M, 6, M + 12, 38), 4, fill=color)
    f = font('Montserrat', 'ExtraBold', 30)
    d.text((M + 28, 4), SECCION, font=f, fill=WHITE)
    d.text((M + 28 + d.textlength(SECCION, font=f), 4), '  ·  ' + fecha, font=font('Montserrat', 'SemiBold', 30), fill=CLARO)
    return im


def _preparar_escena(e, spec, portada_img):
    tipo, color = e['tipo'], TONOS.get(e.get('tono', 'neutro'), ORANGE)
    capas = []  # (imagen RGBA, x, y, inicio, duración, modo)
    e['_cab'] = _cabecera_reel(spec.get('fecha', ''), color)
    e['_color'] = color
    if tipo in ('portada', 'noticia'):
        src = e.get('imagen_reel') or e.get('imagen')
        img = _imagen(src) if src and src != spec['_portada_src'] else portada_img
        if img is not None:
            e['_bg'] = _cover(img, round(RW * 1.1), round(IMG_H * 1.1))
        ov = Image.new('RGBA', (RW, IMG_H), BG + (0,))
        ov.alpha_composite(_degradado(RW, 520, BG), (0, IMG_H - 520))
        ov.alpha_composite(_degradado(RW, 300, BG, 210).transpose(Image.FLIP_TOP_BOTTOM), (0, 0))
        e['_ov'] = ov
        chip = _capa_chip(e.get('etiqueta', 'ÚLTIMA HORA' if tipo == 'portada' else 'NOTICIA'), color)
        # La portada es el gancho: titular visible desde el primer fotograma, sin fundido ni destello.
        # El subtítulo de la slide no va en el reel: lo sustituyen los subtítulos de la voz.
        modo = 'fijo' if tipo == 'portada' else 'fade'
        capas.append((chip, M, 1045, 0.0, 0.25, modo))
        if tipo == 'portada':
            t = _capa_texto(e['titulo'], 'Montserrat', 'ExtraBold', 100, RTXT, 4, 64, WHITE, 1.06)
        else:
            t = _capa_texto(e['titulo'], 'Montserrat', 'ExtraBold', 84, RTXT, 3, 56, WHITE, 1.08)
        capas.append((t, M, 1130, 0.08, 0.35, modo))
        e['_sub_y'] = 860
    elif tipo == 'dato':
        fondo = Image.new('RGBA', (RW, RH), BG + (255,))
        halo = Image.new('RGBA', (RW, RH), BG + (0,))
        ImageDraw.Draw(halo).ellipse((RW // 2 - 480, 560, RW // 2 + 480, 1260), fill=color + (70,))
        fondo.alpha_composite(halo.filter(ImageFilter.GaussianBlur(150)))
        e['_fijo'] = fondo.convert('RGB')
        chip = _capa_chip(e.get('etiqueta', 'EL DATO'), color)
        capas.append((chip, M, 520, 0.0, 0.25, 'fade'))
        num = _capa_texto(e['dato'], 'Montserrat', 'ExtraBold', 220, RW - 2 * M, 2, 110, color, 1.0)
        capas.append((num, M, 620, 0.1, 0.45, 'pop'))
        y = 620 + num.height + 30
        barra = Image.new('RGBA', (120, 10), color + (255,))
        capas.append((barra, M, y, 0.35, 0.3, 'fade'))
        t = _capa_texto(e['titulo'], 'Montserrat', 'ExtraBold', 72, RTXT, 3, 48, WHITE, 1.08)
        capas.append((t, M, y + 50, 0.4, 0.35, 'fade'))
        e['_sub_y'] = min(1420, y + 50 + t.height + 50)  # subtítulos justo debajo del contenido
    else:  # cierre
        e['_fijo'] = Image.new('RGB', (RW, RH), BG)
        anillo = Image.new('RGBA', (200, 200), (0, 0, 0, 0))
        da = ImageDraw.Draw(anillo)
        da.ellipse((5, 5, 195, 195), outline=ORANGE, width=7)
        da.text((100, 100), '₿', font=font('Montserrat', 'ExtraBold', 116), fill=ORANGE, anchor='mm')
        capas.append((anillo, RW // 2 - 100, 480, 0.0, 0.4, 'pop'))
        t = _capa_texto(e.get('titulo', 'Síguenos para estar al día'), 'Montserrat', 'ExtraBold', 80, RW - 2 * M, 3, 54, WHITE, 1.1, True)
        capas.append((t, M, 760, 0.15, 0.35, 'fade'))
        y = 760 + t.height + 30
        h = _capa_texto(spec.get('handle', '@raycriptodiario'), 'Montserrat', 'ExtraBold', 60, RW - 2 * M, 1, 40, ORANGE, 1.1, True)
        capas.append((h, M, y, 0.35, 0.35, 'fade'))
        dy = _capa_texto('Esto no es consejo financiero · DYOR', 'Inter', 'Medium', 30, RW - 2 * M, 1, 24, MUTED, 1.2, True)
        capas.append((dy, M, 1500, 0.7, 0.35, 'fade'))
        e['_sub_y'] = 1290
    e['_capas'] = capas


# ---------- subtítulos de la voz (la mayoría ve los reels sin sonido) ----------
_FSUB = {}


def _bloques_sub(palabras, desfase, por_bloque=3):
    # Agrupa las palabras de 3 en 3; cada bloque se ve desde su primera palabra hasta que empieza el siguiente.
    bloques = []
    for k in range(0, len(palabras), por_bloque):
        grupo = [(a + desfase, b + desfase, p) for a, b, p in palabras[k:k + por_bloque]]
        bloques.append([grupo[0][0], grupo[-1][1] + 0.35, grupo])
    for k in range(len(bloques) - 1):
        bloques[k][1] = bloques[k + 1][0]
    return bloques


def _subtitulo(c, e, lt):
    bloque = next((b for b in e.get('_subs', []) if b[0] <= lt < b[1]), None)
    if not bloque:
        return
    d = ImageDraw.Draw(c)
    size = 74
    while True:
        f = _FSUB.get(size) or _FSUB.setdefault(size, font('Montserrat', 'ExtraBold', size))
        esp = d.textlength(' ', font=f)
        anchos = [d.textlength(p, font=f) for _, _, p in bloque[2]]
        total = sum(anchos) + esp * (len(anchos) - 1)
        if total <= RW - 2 * M or size <= 44:
            break
        size -= 4
    x, y = (RW - total) / 2, e['_sub_y']
    for (a, b, p), w in zip(bloque[2], anchos):
        actual = a <= lt < b + 0.08
        d.text((x, y), p, font=f, fill=ORANGE if actual else WHITE, stroke_width=7, stroke_fill=(0, 0, 0))
        x += w + esp


def _frame(e, lt):
    p = min(1.0, lt / e['dur'])
    if e.get('_fijo') is not None:
        c = e['_fijo'].copy()
    else:
        c = Image.new('RGB', (RW, RH), BG)
        bg = e.get('_bg')
        if bg is not None:
            z = 1 + 0.08 * _ease(p)  # zoom lento hacia dentro (efecto Ken Burns)
            w, h = bg.width / z, bg.height / z
            x0, y0 = (bg.width - w) / 2, (bg.height - h) / 2
            c.paste(bg.resize((RW, IMG_H), Image.BILINEAR, box=(x0, y0, x0 + w, y0 + h)), (0, 0))
        c.paste(e['_ov'], (0, 0), e['_ov'])
    c.paste(e['_cab'], (0, 78), e['_cab'])
    for im, x, y, t0, d, modo in e['_capas']:
        k = 1.0 if modo == 'fijo' else max(0.0, min(1.0, (lt - t0) / d))
        if k <= 0:
            continue
        if k >= 1:
            c.paste(im, (x, y), im)
        elif modo == 'pop':
            s = max(0.05, _back(k))
            im2 = im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.BILINEAR)
            a = im2.getchannel('A').point(lambda v: round(v * min(1, k * 2)))
            c.paste(im2, (x + (im.width - im2.width) // 2, y + (im.height - im2.height) // 2), a)
        else:
            a = im.getchannel('A').point(lambda v: round(v * k))
            c.paste(im, (x, y + round((1 - _ease(k)) * 40)), a)
    _subtitulo(c, e, lt)
    return c


def _barra(c, i, p, n):
    # barra de progreso arriba, un segmento por escena (como las historias): ayuda a que se vea hasta el final
    d = ImageDraw.Draw(c)
    gap, x = 8, 24
    ancho = (RW - 48 - gap * (n - 1)) / n
    for j in range(n):
        x0 = 24 + j * (ancho + gap)
        d.rounded_rectangle((x0, 30, x0 + ancho, 38), 4, fill=(90, 100, 120))
        lleno = ancho if j < i else (ancho * p if j == i else 0)
        if lleno > 0:
            d.rounded_rectangle((x0, 30, x0 + max(8, lleno), 38), 4, fill=WHITE)


def preparar_reel(spec):
    global SECCION
    SECCION = spec.get('seccion', 'CRIPTO AL MOMENTO').upper()
    _fuentes()
    shutil.rmtree(REEL_DIR, ignore_errors=True)
    os.makedirs(REEL_DIR + '/frames')
    voz = {**VOZ_REEL, **spec.get('voz_reel', {})}
    # Solo entran en el reel las slides con "voz" (lo normal: 5 de las 7 del carrusel, para 15-20 s).
    escenas = [dict(s) for s in spec['slides'] if s.get('voz')] or [dict(s) for s in spec['slides']]
    with ThreadPoolExecutor(5) as ex:
        futs = {i: ex.submit(_locucion, i, e['voz'], voz) for i, e in enumerate(escenas) if e.get('voz')}
        portada_src = escenas[0].get('imagen_reel') or escenas[0].get('imagen')
        f_portada = ex.submit(_imagen, portada_src) if portada_src else None
        for i, f in futs.items():
            try:
                escenas[i]['wav'], escenas[i]['_palabras'] = f.result()
                escenas[i]['voz_dur'] = _dur(escenas[i]['wav'])
            except Exception as err:
                escenas[i]['error_voz'] = str(err)[:200]
        portada_img = f_portada.result() if f_portada else None
    t = 0.0
    for i, e in enumerate(escenas):
        arranque = 0.05 if i == 0 else 0.2  # la voz del gancho empieza ya
        e['ini'], e['voz_ini'] = t, t + arranque
        e['dur'] = max(2.8 if e['tipo'] == 'cierre' else 2.0, arranque + e.get('voz_dur', 0) + 0.3)
        if e.get('wav'):
            palabras = e.get('_palabras') or _palabras_repartidas(e['voz'], e['voz_dur'])
            e['_subs'] = _bloques_sub(palabras, arranque)
        t += e['dur']
    total = t + 0.3
    escenas[-1]['dur'] += 0.3
    spec = {**spec, '_portada_src': portada_src}
    for e in escenas:
        _preparar_escena(e, spec, portada_img)
    audio = _mezcla(escenas, total, spec.get('musica', True))
    _R.clear()
    _R.update(escenas=escenas, total=total, nframes=math.ceil(total * FPS), siguiente=0,
              actual=0, previo=None, ultimo=None, audio=audio)
    return {'duracion_s': round(total, 1), 'fotogramas': _R['nframes'],
            'thumb_offset_ms': 500,  # portada con el titular ya visible
            'escenas': [(e['tipo'], round(e['dur'], 1), 'voz ok' if e.get('wav') else e.get('error_voz', 'sin voz'))
                        for e in escenas]}


def renderizar_reel(max_seg=150):
    # Genera fotogramas hasta agotar max_seg; devuelve True cuando ha terminado.
    t0 = time.time()
    E = _R['escenas']
    while _R['siguiente'] < _R['nframes']:
        if time.time() - t0 > max_seg:
            print(f"fotogramas {_R['siguiente']}/{_R['nframes']}: llama otra vez a renderizar_reel()")
            return False
        n = _R['siguiente']
        t = n / FPS
        i = max(j for j, e in enumerate(E) if e['ini'] <= t + 1e-6)
        if i != _R['actual']:
            _R['previo'], _R['actual'] = _R['ultimo'], i
        e = E[i]
        lt = t - e['ini']
        img = _frame(e, lt)
        if i > 0 and lt < 0.2 and _R['previo'] is not None:  # fundido corto entre escenas
            img = Image.blend(_R['previo'], img, lt / 0.2)
        _barra(img, i, min(1, lt / e['dur']), len(E))
        # se guarda a través de BytesIO: con img.save(ruta) el workbench muestra cada fotograma en la salida
        buf = io.BytesIO()
        img.save(buf, 'JPEG', quality=88)
        with open(f'{REEL_DIR}/frames/f{n:05d}.jpg', 'wb') as fh:
            fh.write(buf.getvalue())
        _R['ultimo'] = img
        _R['siguiente'] += 1
    return True


def codificar_reel():
    # ultrafast y un solo hilo: con presets más lentos o más hilos el sandbox se queda sin memoria y se reinicia
    salida = f'{REEL_DIR}/reel.mp4'
    cmd = [_ff(), '-y', '-hide_banner', '-loglevel', 'error', '-framerate', str(FPS), '-i', f'{REEL_DIR}/frames/f%05d.jpg',
           '-i', _R['audio'], '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'stillimage',
           '-crf', '20', '-pix_fmt', 'yuv420p', '-threads', '1', '-c:a', 'aac', '-b:a', '160k', '-shortest',
           '-movflags', '+faststart', salida]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=170)
    if r.returncode:
        raise RuntimeError(r.stderr[-500:])
    return salida


def subir_video(ruta):
    res, err = upload_local_file(ruta)
    if err:
        raise RuntimeError(err)
    data = res.get('data', res) if isinstance(res, dict) else {}
    return {'name': 'reel.mp4', 'mimetype': 'video/mp4', 's3key': data.get('s3key'), 'url': data.get('s3_url')}
