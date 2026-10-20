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
# spec: el mismo del carrusel, con un campo "voz" en cada slide: lo que dice Álvaro (1-2 frases cortas).
#   Opcionales: "imagen_reel" en una slide (ilustración vertical que sustituye a "imagen"),
#               spec["voz_reel"] = {"nombre": "es-ES-AlvaroNeural", "rate": "+20%", "pitch": "+2Hz"},
#               spec["musica"] = False para quitar la base musical (por defecto va, generada por código y sin derechos).
# Una slide noticia sin imagen reutiliza la ilustración de la portada.

import asyncio, math, re, shutil, subprocess, sys, time, wave
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
    edge_tts = _pip('edge_tts', 'edge-tts')

    async def go():
        await edge_tts.Communicate(texto, voz['nombre'], rate=voz['rate'], pitch=voz['pitch']).save(mp3)
    asyncio.run(go())  # se llama desde un hilo, así no choca con el bucle de Jupyter


def _locucion(i, texto, voz):
    mp3, wav = f'{REEL_DIR}/voz{i}.mp3', f'{REEL_DIR}/voz{i}.wav'
    err = None
    for _ in range(2):
        try:
            _tts(texto, mp3, voz)
            err = None
            break
        except Exception as e:
            err = e
            time.sleep(2)
    if err:
        raise err
    # Edge deja casi 1 s de pausa en los ":" y "…" y al final: se recortan a 0,2 s para que el reel tenga ritmo.
    subprocess.run([_ff(), '-y', '-hide_banner', '-loglevel', 'error', '-i', mp3, '-af',
                    'silenceremove=start_periods=1:start_threshold=-42dB:stop_periods=-1:stop_duration=0.2'
                    ':stop_threshold=-42dB:stop_silence=0.18,aresample=48000', '-ac', '1', wav], check=True)
    return wav


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
        capas.append((chip, M, 1045, 0.0, 0.25, 'fade'))
        if tipo == 'portada':
            t = _capa_texto(e['titulo'], 'Montserrat', 'ExtraBold', 96, RTXT, 4, 64, WHITE, 1.06)
        else:
            t = _capa_texto(e['titulo'], 'Montserrat', 'ExtraBold', 84, RTXT, 3, 56, WHITE, 1.08)
        capas.append((t, M, 1130, 0.08, 0.35, 'fade'))
        if e.get('subtitulo'):
            s = _capa_texto(e['subtitulo'], 'Inter', 'Regular', 42, RTXT, 4, 32, CLARO, 1.3)
            capas.append((s, M, 1130 + t.height + 24, 0.4, 0.35, 'fade'))
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
        if e.get('subtitulo'):
            s = _capa_texto(e['subtitulo'], 'Inter', 'Regular', 42, RTXT, 4, 32, CLARO, 1.3)
            capas.append((s, M, y + 50 + t.height + 20, 0.6, 0.35, 'fade'))
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
        sub = e.get('subtitulo', 'Guarda este post y compártelo con quien esté empezando en cripto')
        s = _capa_texto(sub, 'Inter', 'Regular', 38, RW - 2 * M - 80, 3, 30, CLARO, 1.35, True)
        capas.append((s, M + 40, y + h.height + 40, 0.55, 0.35, 'fade'))
        dy = _capa_texto('Esto no es consejo financiero · DYOR', 'Inter', 'Medium', 30, RW - 2 * M, 1, 24, MUTED, 1.2, True)
        capas.append((dy, M, 1500, 0.7, 0.35, 'fade'))
    e['_capas'] = capas


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
        k = max(0.0, min(1.0, (lt - t0) / d))
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
    escenas = [dict(s) for s in spec['slides']]
    with ThreadPoolExecutor(4) as ex:
        futs = {i: ex.submit(_locucion, i, e['voz'], voz) for i, e in enumerate(escenas) if e.get('voz')}
        portada_src = escenas[0].get('imagen_reel') or escenas[0].get('imagen')
        f_portada = ex.submit(_imagen, portada_src) if portada_src else None
        for i, f in futs.items():
            try:
                escenas[i]['wav'] = f.result()
                escenas[i]['voz_dur'] = _dur(escenas[i]['wav'])
            except Exception as err:
                escenas[i]['error_voz'] = str(err)[:200]
        portada_img = f_portada.result() if f_portada else None
    t = 0.0
    for i, e in enumerate(escenas):
        arranque = 0.15 if i == 0 else 0.25
        e['ini'], e['voz_ini'] = t, t + arranque
        e['dur'] = max(3.2 if e['tipo'] == 'cierre' else 2.4, arranque + e.get('voz_dur', 0) + 0.35)
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
            'thumb_offset_ms': 900,  # portada con el titular ya visible
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
        if i == 0 and lt < 0.25:  # destello de entrada
            img = Image.blend(img, Image.new('RGB', (RW, RH), WHITE), 0.7 * (1 - lt / 0.25))
        elif i > 0 and lt < 0.2 and _R['previo'] is not None:  # fundido corto entre escenas
            img = Image.blend(_R['previo'], img, lt / 0.2)
        _barra(img, i, min(1, lt / e['dur']), len(E))
        img.save(f'{REEL_DIR}/frames/f{n:05d}.jpg', 'JPEG', quality=88)
        _R['ultimo'] = img
        _R['siguiente'] += 1
    return True


def codificar_reel(preset='veryfast'):
    salida = f'{REEL_DIR}/reel.mp4'
    cmd = [_ff(), '-y', '-hide_banner', '-loglevel', 'error', '-framerate', str(FPS), '-i', f'{REEL_DIR}/frames/f%05d.jpg',
           '-i', _R['audio'], '-map', '0:v', '-map', '1:a', '-c:v', 'libx264', '-preset', preset, '-crf', '21',
           '-pix_fmt', 'yuv420p', '-threads', '2', '-c:a', 'aac', '-b:a', '160k', '-shortest', '-movflags', '+faststart', salida]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=165)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"ffmpeg tardó demasiado con preset {preset}: llama a codificar_reel('ultrafast') en otra celda")
    if r.returncode:
        if preset != 'ultrafast':
            raise RuntimeError(f"ffmpeg falló con {preset} ({r.stderr[-300:]}): llama a codificar_reel('ultrafast') en otra celda")
        raise RuntimeError(r.stderr[-500:])
    return salida


def subir_video(ruta):
    res, err = upload_local_file(ruta)
    if err:
        raise RuntimeError(err)
    data = res.get('data', res) if isinstance(res, dict) else {}
    return {'name': 'reel.mp4', 'mimetype': 'video/mp4', 's3key': data.get('s3key'), 'url': data.get('s3_url')}
