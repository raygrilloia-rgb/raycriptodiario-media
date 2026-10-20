# Plantilla de marca de @raycriptodiario para carruseles e historias.
# Se ejecuta en COMPOSIO_REMOTE_WORKBENCH (Pillow 11). Gemini genera solo la
# ilustración (sin texto); este script pone siempre el mismo marco, tipografía y colores.
#
# Uso en el workbench:
#   exec(open('/mnt/files/plantilla/render_slides.py').read())   # o pegar este archivo
#   archivos = render_post(spec)        # devuelve rutas JPEG locales del sandbox
#   refs = subir(archivos)              # devuelve [{name, mimetype, s3key}] para image_file
#
# spec = {
#   "fecha": "18 OCT", "handle": "@raycriptodiario",
#   "slides": [
#     {"tipo": "portada", "titulo": "...", "etiqueta": "ÚLTIMA HORA", "tono": "alerta", "imagen": "<url o ruta>"},
#     {"tipo": "noticia", "titulo": "...", "subtitulo": "...", "etiqueta": "HACKEO", "tono": "alerta", "imagen": "..."},
#     {"tipo": "dato", "dato": "36.818 BTC", "titulo": "...", "subtitulo": "comparación", "etiqueta": "EL DATO", "tono": "neutro"},
#     {"tipo": "cierre", "titulo": "pregunta final (opcional)", "subtitulo": "CTA (opcional)"}
#   ],
#   "historia": True   # genera también historia.jpg (1080x1920) a partir de la portada
# }
# tono: alerta (rojo) · aviso (ámbar) · positivo (verde) · neutro (naranja Bitcoin)

import io, os, requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FONT_DIR = '/mnt/files/plantilla/fonts'
OUT_DIR = '/mnt/files/plantilla/out'
FONT_URLS = {
    'Montserrat.ttf': 'https://github.com/google/fonts/raw/main/ofl/montserrat/Montserrat%5Bwght%5D.ttf',
    'Inter.ttf': 'https://github.com/google/fonts/raw/main/ofl/inter/Inter%5Bopsz%2Cwght%5D.ttf',
}

W, H = 1080, 1350          # 4:5, el formato de feed que más ocupa en pantalla
SW, SH = 1080, 1920        # historia 9:16
M = 72                     # margen lateral
SECCION = 'CRIPTO AL MOMENTO'  # cabecera; se cambia con spec['seccion'] (p. ej. 'CURIOSIDAD CRIPTO')

BG = (10, 18, 34)
PANEL = (20, 31, 54)
WHITE = (255, 255, 255)
MUTED = (169, 180, 200)
ORANGE = (247, 147, 26)
TONOS = {
    'alerta': (255, 77, 79),
    'aviso': (255, 176, 32),
    'positivo': (34, 197, 94),
    'neutro': ORANGE,
}


def _fuentes():
    os.makedirs(FONT_DIR, exist_ok=True)
    for n, u in FONT_URLS.items():
        p = os.path.join(FONT_DIR, n)
        if not os.path.exists(p):
            open(p, 'wb').write(requests.get(u, timeout=60).content)


def font(familia, peso, size):
    f = ImageFont.truetype(os.path.join(FONT_DIR, familia + '.ttf'), size)
    f.set_variation_by_name(peso)
    return f


def _imagen(src):
    if not src:
        return None
    if str(src).startswith('http'):
        return Image.open(io.BytesIO(requests.get(src, timeout=60).content)).convert('RGB')
    return Image.open(src).convert('RGB')


def _cover(img, w, h):
    r = max(w / img.width, h / img.height)
    img = img.resize((round(img.width * r), round(img.height * r)), Image.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))


def _redondear(img, radio):
    mask = Image.new('L', img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, img.width, img.height), radio, fill=255)
    out = Image.new('RGBA', img.size)
    out.paste(img, (0, 0), mask)
    return out


def _wrap(draw, texto, f, ancho):
    lineas, actual = [], ''
    for palabra in texto.split():
        prueba = (actual + ' ' + palabra).strip()
        if draw.textlength(prueba, font=f) <= ancho:
            actual = prueba
        else:
            if actual:
                lineas.append(actual)
            actual = palabra
    if actual:
        lineas.append(actual)
    return lineas


def _equilibrar(draw, texto, f, ancho):
    # Estrecha el ancho mientras no aumente el número de líneas, para que no quede una palabra sola.
    n = len(_wrap(draw, texto, f, ancho))
    w = ancho
    while n > 1 and w > ancho * 0.5 and len(_wrap(draw, texto, f, w - 20)) == n:
        w -= 20
    return _wrap(draw, texto, f, w)


def _bloque(draw, texto, familia, peso, size, ancho, max_lineas, min_size):
    # Reduce el tamaño hasta que el texto quepa en max_lineas.
    while True:
        f = font(familia, peso, size)
        lineas = _wrap(draw, texto, f, ancho)
        if len(lineas) <= max_lineas or size <= min_size:
            return f, _equilibrar(draw, texto, f, ancho)[:max_lineas]
        size -= 4


def _texto(draw, xy, lineas, f, color, interlineado=1.12):
    x, y = xy
    alto = round(f.size * interlineado)
    for l in lineas:
        draw.text((x, y), l, font=f, fill=color)
        y += alto
    return y


def _degradado(w, h, desde, hasta_alpha=255):
    # Degradado vertical transparente -> color de fondo.
    g = Image.new('L', (1, h))
    for y in range(h):
        t = y / max(h - 1, 1)
        g.putpixel((0, y), round(hasta_alpha * (t ** 1.6)))
    g = g.resize((w, h))
    capa = Image.new('RGBA', (w, h), desde + (0,))
    capa.putalpha(g)
    return capa


def _chip(draw, xy, texto, color):
    f = font('Montserrat', 'ExtraBold', 26)
    tw = draw.textlength(texto, font=f)
    x, y = xy
    fondo = tuple(round(c * 0.22 + b * 0.78) for c, b in zip(color, BG))
    draw.rounded_rectangle((x, y, x + tw + 44, y + 52), 26, fill=fondo, outline=color, width=2)
    draw.text((x + 22, y + 11), texto, font=f, fill=color)
    return y + 52


def _cabecera(draw, fecha, n=None, total=None, color=ORANGE):
    draw.rounded_rectangle((M, 64, M + 14, 64 + 34), 4, fill=color)
    f = font('Montserrat', 'ExtraBold', 28)
    draw.text((M + 30, 64), SECCION, font=f, fill=WHITE)
    x = M + 30 + draw.textlength(SECCION, font=f)
    draw.text((x, 64), '  ·  ' + fecha, font=font('Montserrat', 'SemiBold', 28), fill=MUTED)
    if n and total:
        t = f'{n}/{total}'
        fi = font('Inter', 'SemiBold', 28)
        draw.text((W - M - draw.textlength(t, font=fi), 64), t, font=fi, fill=MUTED)


def _pie(draw, handle, alto, desliza=True):
    y = alto - 64 - 30
    draw.line((M, y - 28, W - M, y - 28), fill=PANEL, width=2)
    draw.text((M, y), handle, font=font('Inter', 'SemiBold', 30), fill=ORANGE)
    if desliza:
        t = 'Desliza →'
        fi = font('Inter', 'Medium', 30)
        draw.text((W - M - draw.textlength(t, font=fi), y), t, font=fi, fill=MUTED)


def slide_portada(s, fecha, handle, total):
    color = TONOS.get(s.get('tono', 'neutro'), ORANGE)
    lienzo = Image.new('RGB', (W, H), BG)
    img = _imagen(s.get('imagen'))
    if img:
        lienzo.paste(_cover(img, W, 900), (0, 0))
    lienzo = lienzo.convert('RGBA')
    lienzo.alpha_composite(_degradado(W, 520, BG), (0, 380))
    lienzo.alpha_composite(_degradado(W, 240, BG, 220).transpose(Image.FLIP_TOP_BOTTOM), (0, 0))
    d = ImageDraw.Draw(lienzo)
    _cabecera(d, fecha, 1, total, color)
    y = _chip(d, (M, 760), s.get('etiqueta', 'ÚLTIMA HORA'), color)
    f, lineas = _bloque(d, s['titulo'], 'Montserrat', 'ExtraBold', 92, W - 2 * M, 3, 60)
    _texto(d, (M, y + 28), lineas, f, WHITE, 1.08)
    _pie(d, handle, H, desliza=total > 1)
    return lienzo.convert('RGB')


def slide_noticia(s, fecha, handle, n, total):
    color = TONOS.get(s.get('tono', 'neutro'), ORANGE)
    lienzo = Image.new('RGBA', (W, H), BG + (255,))
    d = ImageDraw.Draw(lienzo)
    _cabecera(d, fecha, n, total, color)
    caja = (M, 140, W - M, 140 + 600)
    img = _imagen(s.get('imagen'))
    if img:
        ilus = _redondear(_cover(img, caja[2] - caja[0], caja[3] - caja[1]), 36)
        lienzo.alpha_composite(ilus, (caja[0], caja[1]))
    else:
        d.rounded_rectangle(caja, 36, fill=PANEL)
    d.rounded_rectangle(caja, 36, outline=color, width=3)
    y = _chip(d, (M, caja[3] + 44), s.get('etiqueta', 'NOTICIA'), color)
    f, lineas = _bloque(d, s['titulo'], 'Montserrat', 'ExtraBold', 64, W - 2 * M, 3, 44)
    y = _texto(d, (M, y + 26), lineas, f, WHITE, 1.1)
    if s.get('subtitulo'):
        fs, ls = _bloque(d, s['subtitulo'], 'Inter', 'Regular', 36, W - 2 * M, 3, 28)
        _texto(d, (M, y + 14), ls, fs, MUTED, 1.3)
    _pie(d, handle, H, desliza=n < total)
    return lienzo.convert('RGB')


def slide_dato(s, fecha, handle, n, total):
    # Slide sin ilustración: una cifra enorme que impacta y su explicación.
    # Campos: 'dato' (p. ej. "36.818 BTC"), 'titulo' (qué significa la cifra), 'subtitulo' (comparación o contexto).
    color = TONOS.get(s.get('tono', 'neutro'), ORANGE)
    lienzo = Image.new('RGBA', (W, H), BG + (255,))
    # Halo suave del color del tono detrás de la cifra
    halo = Image.new('RGBA', (W, H), BG + (0,))
    ImageDraw.Draw(halo).ellipse((W // 2 - 460, 260, W // 2 + 460, 900), fill=color + (60,))
    lienzo.alpha_composite(halo.filter(ImageFilter.GaussianBlur(140)))
    d = ImageDraw.Draw(lienzo)
    _cabecera(d, fecha, n, total, color)
    y = _chip(d, (M, 230), s.get('etiqueta', 'EL DATO'), color)
    fd, ld = _bloque(d, s['dato'], 'Montserrat', 'ExtraBold', 210, W - 2 * M, 2, 110)
    y = _texto(d, (M, y + 50), ld, fd, color, 1.0)
    d.rounded_rectangle((M, y + 30, M + 120, y + 40), 5, fill=color)
    f, lineas = _bloque(d, s['titulo'], 'Montserrat', 'ExtraBold', 64, W - 2 * M, 3, 44)
    y = _texto(d, (M, y + 80), lineas, f, WHITE, 1.1)
    if s.get('subtitulo'):
        fs, ls = _bloque(d, s['subtitulo'], 'Inter', 'Regular', 38, W - 2 * M, 4, 28)
        _texto(d, (M, y + 20), ls, fs, MUTED, 1.3)
    _pie(d, handle, H, desliza=n < total)
    return lienzo.convert('RGB')


def slide_cierre(s, fecha, handle, n, total):
    lienzo = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(lienzo)
    _cabecera(d, fecha, n, total)
    d.ellipse((W // 2 - 90, 330, W // 2 + 90, 510), outline=ORANGE, width=6)
    fb = font('Montserrat', 'ExtraBold', 110)
    d.text((W // 2, 420), '₿', font=fb, fill=ORANGE, anchor='mm')
    f, lineas = _bloque(d, s.get('titulo', 'Síguenos para estar al día'), 'Montserrat', 'ExtraBold', 76, W - 2 * M, 2, 52)
    y = 580
    for l in lineas:
        d.text((W // 2, y), l, font=f, fill=WHITE, anchor='ma')
        y += round(f.size * 1.1)
    d.text((W // 2, y + 30), handle, font=font('Montserrat', 'ExtraBold', 56), fill=ORANGE, anchor='ma')
    sub = s.get('subtitulo', 'Guarda este post y compártelo con quien esté empezando en cripto')
    fs, ls = _bloque(d, sub, 'Inter', 'Regular', 34, W - 2 * M - 80, 2, 28)
    y += 150
    for l in ls:
        d.text((W // 2, y), l, font=fs, fill=MUTED, anchor='ma')
        y += round(fs.size * 1.35)
    d.text((W // 2, H - 150), 'Esto no es consejo financiero · DYOR', font=font('Inter', 'Medium', 28), fill=MUTED, anchor='ma')
    return lienzo


def historia(s, fecha, handle):
    color = TONOS.get(s.get('tono', 'neutro'), ORANGE)
    lienzo = Image.new('RGB', (SW, SH), BG)
    img = _imagen(s.get('imagen_historia') or s.get('imagen'))
    if img:
        # La ilustración empieza bajo la cabecera para que nada tape la fecha.
        lienzo.paste(_cover(img, SW, 1030), (0, 230))
    lienzo = lienzo.convert('RGBA')
    lienzo.alpha_composite(_degradado(SW, 660, BG), (0, 610))
    lienzo.alpha_composite(_degradado(SW, 220, BG).transpose(Image.FLIP_TOP_BOTTOM), (0, 230))
    d = ImageDraw.Draw(lienzo)
    d.rounded_rectangle((M, 150, M + 14, 150 + 34), 4, fill=color)
    f = font('Montserrat', 'ExtraBold', 30)
    d.text((M + 30, 150), SECCION, font=f, fill=WHITE)
    x = M + 30 + d.textlength(SECCION, font=f)
    d.text((x, 150), '  ·  ' + fecha, font=font('Montserrat', 'SemiBold', 30), fill=MUTED)
    y = _chip(d, (M, 1150), s.get('etiqueta', 'ÚLTIMA HORA'), color)
    by = SH - 330
    # El titular se reduce hasta dejar al menos 60 px libres sobre el botón.
    size = 100
    while True:
        ft, lineas = _bloque(d, s['titulo'], 'Montserrat', 'ExtraBold', size, SW - 2 * M, 4, size)
        alto = len(lineas) * round(ft.size * 1.08)
        if y + 30 + alto <= by - 60 or size <= 60:
            break
        size -= 4
    y = _texto(d, (M, y + 30), lineas, ft, WHITE, 1.08)
    # Botón hacia el post (la zona inferior de 250 px queda libre para la interfaz de Instagram).
    fb = font('Montserrat', 'ExtraBold', 34)
    t = 'NUEVO POST EN EL PERFIL  →'
    tw = d.textlength(t, font=fb)
    d.rounded_rectangle((SW // 2 - tw / 2 - 40, by, SW // 2 + tw / 2 + 40, by + 84), 42, fill=ORANGE)
    d.text((SW // 2, by + 42), t, font=fb, fill=BG, anchor='mm')
    d.text((SW // 2, by + 120), handle, font=font('Inter', 'SemiBold', 32), fill=MUTED, anchor='ma')
    return lienzo.convert('RGB')


def render_post(spec):
    global SECCION
    SECCION = spec.get('seccion', 'CRIPTO AL MOMENTO').upper()
    _fuentes()
    os.makedirs(OUT_DIR, exist_ok=True)
    fecha, handle = spec.get('fecha', ''), spec.get('handle', '@raycriptodiario')
    slides = spec['slides']
    total = len(slides)
    rutas = []
    for i, s in enumerate(slides, 1):
        if s['tipo'] == 'portada':
            img = slide_portada(s, fecha, handle, total)
        elif s['tipo'] == 'cierre':
            img = slide_cierre(s, fecha, handle, i, total)
        elif s['tipo'] == 'dato':
            img = slide_dato(s, fecha, handle, i, total)
        else:
            img = slide_noticia(s, fecha, handle, i, total)
        p = os.path.join(OUT_DIR, f'slide{i}.jpg')
        img.save(p, 'JPEG', quality=92, optimize=True)
        rutas.append(p)
    if spec.get('historia'):
        p = os.path.join(OUT_DIR, 'historia.jpg')
        historia(slides[0], fecha, handle).save(p, 'JPEG', quality=92, optimize=True)
        rutas.append(p)
    return rutas


def subir(rutas):
    # upload_local_file es un helper del workbench de Composio.
    refs = []
    for p in rutas:
        res, err = upload_local_file(p)
        if err:
            raise RuntimeError(f'{p}: {err}')
        data = res.get('data', res) if isinstance(res, dict) else {}
        refs.append({'name': os.path.basename(p), 'mimetype': 'image/jpeg',
                     's3key': data.get('s3key'), 'url': data.get('s3_url')})
    return refs
