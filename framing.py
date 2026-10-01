"""Where to crop a still so it fills a 9:16 Short: the window with the most detail (edges, colour),
nudged toward the upper middle where faces and action usually sit. Pure numpy, no models."""
import numpy as np
from PIL import Image, ImageFilter


def _energy(im, size=256):
    s = size / max(im.size)
    sm = im.convert("RGB").resize((max(8, int(im.width * s)), max(8, int(im.height * s))), Image.BILINEAR)
    a = np.asarray(sm, dtype=np.float32) / 255.0
    g = a.mean(axis=2)
    edges = np.abs(np.diff(g, axis=1, prepend=g[:, :1])) + np.abs(np.diff(g, axis=0, prepend=g[:1, :]))
    sat = a.max(axis=2) - a.min(axis=2)
    e = edges / (edges.mean() + 1e-6) + 0.6 * sat / (sat.mean() + 1e-6)
    e = np.asarray(Image.fromarray((e / (e.max() + 1e-6) * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(3)),
                   dtype=np.float32)
    h, w = e.shape
    yy = np.linspace(0, 1, h)[:, None]
    xx = np.linspace(0, 1, w)[None, :]
    return e * (1.15 - 0.45 * np.abs(yy - 0.4)) * (1.1 - 0.4 * np.abs(xx - 0.5)), s


def crop_box(im, aspect=9 / 16):
    """(x0, y0, x1, y1) in image pixels: the largest aspect-shaped window, placed on the most detailed region."""
    e, s = _energy(im)
    h, w = e.shape
    wh = int(min(h, w / aspect))
    ww = max(1, min(w, int(round(wh * aspect))))
    ii = np.pad(e, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    sums = ii[wh:, ww:] - ii[:-wh, ww:] - ii[wh:, :-ww] + ii[:-wh, :-ww]
    y, x = np.unravel_index(int(np.argmax(sums)), sums.shape)
    x0, y0 = int(x / s), int(y / s)
    bh = min(im.height, int(round(min(im.height, im.width / aspect))))
    bw = min(im.width, int(round(bh * aspect)))
    x0, y0 = min(x0, im.width - bw), min(y0, im.height - bh)
    return (x0, y0, x0 + bw, y0 + bh)


def hook_score(im):
    """How well a picture works as the first frame: colourful (Hasler-Suesstrunk) and with a lot of skin
    (a face filling the crop), measured inside the 9:16 crop the Short will actually show."""
    c = im.convert("RGB").crop(crop_box(im))
    a = np.asarray(c.resize((96, int(96 * c.height / max(1, c.width)))), dtype=np.float32) / 255.0
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    rg, yb = r - g, 0.5 * (r + g) - b
    colour = np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    skin = ((r > 0.35) & (r >= g) & (g >= b * 0.9) & (r - b > 0.06) & (r - b < 0.5) & (r - g < 0.3)).mean()
    return float(colour + 0.5 * min(skin, 0.5))
