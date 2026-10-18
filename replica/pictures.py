"""Score-free pictures of an animation: preview sheets, filmstrips over time and per-colour motion curves.

They are views, not judgements: they let a model see timing, order and easing that a few still frames hide.
Elements are told apart by colour only (palette taken from the target), so white or near-white parts are not
tracked in the curves; the filmstrips still show them.
"""
import numpy as np
from PIL import Image, ImageDraw, ImageFont

CELL = 112        # filmstrip cell width/height (px)
STRIP_COLS = 8
MERGE = 45        # palette colours closer than this (RGB distance) are one element colour
MAX_COLOURS = 6
WHITE_DIFF = 24   # a pixel is foreground when some channel differs from white by more than this


def on_white(path, premultiplied):
    """RGB float array composited on white. AE PNGs are premultiplied; browser PNGs are straight."""
    a = np.asarray(Image.open(path).convert('RGBA'), np.float32)
    alpha = a[..., 3:4] / 255
    rgb = a[..., :3] if premultiplied else a[..., :3] * alpha
    return rgb + 255 * (1 - alpha)


def foreground(img):
    return (255 - img[..., :3].astype(np.int16)).max(axis=2) > WHITE_DIFF


def mean_abs_diff(a_path, a_premultiplied, b_path, b_premultiplied):
    """Mean absolute pixel difference (0-255) of two renders of the same frame."""
    a, b = on_white(a_path, a_premultiplied), on_white(b_path, b_premultiplied)
    if a.shape != b.shape:
        raise ValueError(f'frame size {b.shape[1]}x{b.shape[0]} differs from {a.shape[1]}x{a.shape[0]}')
    return float(np.abs(a - b).mean())


def heatmap(a, b, gain=3):
    """Max channel difference of two RGB arrays: black = identical, yellow/white = large mismatch."""
    d = np.clip(np.abs(a.astype(np.float32) - b.astype(np.float32)).max(2) / 255 * gain, 0, 1)
    rgb = np.stack([np.clip(d * 2, 0, 1), np.clip(d * 2 - 0.5, 0, 1), np.clip(d * 3 - 2, 0, 1)], 2)
    return (rgb * 255).astype(np.uint8)


def _font(size):
    for path in ('/System/Library/Fonts/Supplemental/Arial.ttf', '/System/Library/Fonts/Helvetica.ttc'):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def sheet(rows, columns, out, cell=220):
    """rows: [(label, [HxWx3 arrays])]; columns: header labels. Saves a labelled grid PNG."""
    font, head = _font(14), 24
    image = Image.new('RGB', (120 + cell * len(columns), head + cell * len(rows)), (245, 246, 248))
    draw = ImageDraw.Draw(image)
    for c, name in enumerate(columns):
        draw.text((120 + c * cell + 6, 5), name, fill=(30, 30, 30), font=font)
    for r, (label, panels) in enumerate(rows):
        y = head + r * cell
        draw.text((6, y + 8), label, fill=(30, 30, 30), font=font)
        for c, panel in enumerate(panels):
            p = Image.fromarray(panel)
            p.thumbnail((cell - 8, cell - 8))
            image.paste(p, (120 + c * cell + (cell - p.width) // 2, y + (cell - p.height) // 2))
            draw.rectangle([120 + c * cell, y, 120 + (c + 1) * cell - 1, y + cell - 1], outline=(210, 212, 218))
    image.save(out)
    return out


def load_rgb(path, premultiplied):
    return np.clip(on_white(path, premultiplied), 0, 255).astype(np.uint8)


def sample(n, at_most):
    """Evenly spaced frame indices, first and last included, at most `at_most` of them."""
    if n <= at_most:
        return list(range(n))
    return sorted({round(i * (n - 1) / (at_most - 1)) for i in range(at_most)})


def filmstrip(rows, times, out, max_cells=24):
    """rows: [(label, [HxWx3 arrays, one per time])]. Saves one image per `max_cells` times; returns the paths.
    Each block shows a time header and then one line per row, so target and yours sit directly above each other."""
    font, small = _font(13), _font(11)
    paths = []
    for part, start in enumerate(range(0, len(times), max_cells)):
        idx = list(range(start, min(start + max_cells, len(times))))
        blocks = [idx[i:i + STRIP_COLS] for i in range(0, len(idx), STRIP_COLS)]
        label_w, head = 64, 16
        block_h = head + CELL * len(rows) + 8
        image = Image.new('RGB', (label_w + CELL * STRIP_COLS, block_h * len(blocks)), (245, 246, 248))
        draw = ImageDraw.Draw(image)
        for b, block in enumerate(blocks):
            y0 = b * block_h
            for c, i in enumerate(block):
                draw.text((label_w + c * CELL + 4, y0 + 2), f'{times[i]:.2f}s', fill=(60, 60, 60), font=small)
            for r, (label, frames) in enumerate(rows):
                y = y0 + head + r * CELL
                draw.text((6, y + CELL // 2 - 8), label, fill=(30, 30, 30), font=font)
                for c, i in enumerate(block):
                    p = Image.fromarray(frames[i][:, :, :3])
                    p.thumbnail((CELL - 6, CELL - 6))
                    x = label_w + c * CELL
                    image.paste(p, (x + (CELL - p.width) // 2, y + (CELL - p.height) // 2))
                    draw.rectangle([x, y, x + CELL - 1, y + CELL - 1], outline=(205, 208, 215))
        path = out.with_name(f'{out.stem}_{part + 1}{out.suffix}') if len(times) > max_cells else out
        image.save(path)
        paths.append(path)
    return paths


def palette(frames):
    """Main element colours of the target: frequent 16-level colour bins, merged when closer than MERGE."""
    pix = np.concatenate([f[foreground(f)] for f in frames if foreground(f).any()])
    bins, counts = np.unique((pix // 16).astype(np.int32), axis=0, return_counts=True)
    colours = []
    for i in np.argsort(-counts):
        if counts[i] < 0.004 * len(pix) or len(colours) >= MAX_COLOURS:
            break
        c = bins[i] * 16 + 8
        if all(np.linalg.norm(c - p) > MERGE for p in colours):
            colours.append(c.astype(np.float32))
    return np.array(colours)


def tracks(frames, colours):
    """Per colour and frame: (area share of the canvas, centre x, centre y) in 0..1 canvas units; NaN when absent."""
    out = np.full((len(colours), len(frames), 3), np.nan)
    for t, f in enumerate(frames):
        f = f[::2, ::2, :3]
        h, w = f.shape[:2]
        d = np.linalg.norm(f[:, :, None, :].astype(np.float32) - colours[None, None], axis=3)
        lab = np.where(foreground(f) & (d.min(2) <= 60), d.argmin(2), -1)
        for k in range(len(colours)):
            ys, xs = np.nonzero(lab == k)
            if len(xs) >= 3:
                out[k, t] = (len(xs) / (h * w), xs.mean() / w, ys.mean() / h)
    return out


def motion_curves(times, colours, target, yours, out):
    """One row per element colour, three panels (visible size, x, y) over time. Target = thick coloured line,
    yours = thin black line. A gap means the colour is not visible at that time."""
    font, small = _font(13), _font(11)
    panels = [('visible size', 0), ('x (left → right)', 1), ('y (top → bottom)', 2)]
    pw, ph, left, top = 300, 96, 70, 40
    W, H = left + pw * 3 + 20, top + (ph + 26) * len(colours) + 34
    image = Image.new('RGB', (W, H), (255, 255, 255))
    draw = ImageDraw.Draw(image)
    legend = 'thick coloured = target' + ('   thin black = yours' if yours is not None else '')
    draw.text((left, 8), f'Motion of each element colour over time ({times[0]:.2f}-{times[-1]:.2f} s).  {legend}',
              fill=(30, 30, 30), font=font)
    t0, t1 = times[0], times[-1] or 1
    for k, c in enumerate(colours):
        y0 = top + k * (ph + 26) + 18
        draw.rectangle([8, y0 + ph // 2 - 14, 48, y0 + ph // 2 + 14], fill=tuple(int(v) for v in c), outline=(120, 120, 120))
        for p, (name, dim) in enumerate(panels):
            x0 = left + p * pw
            draw.rectangle([x0, y0, x0 + pw - 16, y0 + ph], outline=(200, 202, 208))
            if k == 0:
                draw.text((x0, y0 - 18), name, fill=(60, 60, 60), font=small)
            series = [target[k, :, dim]] + ([yours[k, :, dim]] if yours is not None else [])
            vals = np.concatenate([s[~np.isnan(s)] for s in series]) if any((~np.isnan(s)).any() for s in series) else np.array([0, 1])
            lo, hi = (0.0, max(vals.max() * 1.1, 1e-4)) if dim == 0 else (0.0, 1.0)
            X = lambda t: x0 + 4 + (t - t0) / (t1 - t0) * (pw - 24)
            Y = lambda v: y0 + ph - 4 - (v - lo) / (hi - lo) * (ph - 8)
            for s, (colour, width) in zip(series, [(tuple(int(v) for v in c), 4), ((20, 20, 20), 1)]):
                run = []
                for t, v in zip(times, s):
                    if np.isnan(v):
                        if len(run) > 1:
                            draw.line(run, fill=colour, width=width)
                        run = []
                    else:
                        run.append((X(t), Y(v)))
                if len(run) > 1:
                    draw.line(run, fill=colour, width=width)
                elif len(run) == 1:
                    draw.ellipse([run[0][0] - 2, run[0][1] - 2, run[0][0] + 2, run[0][1] + 2], fill=colour)
    # time axis under the last row
    yb = top + len(colours) * (ph + 26) + 10
    for p in range(3):
        x0 = left + p * pw
        for frac in (0, 0.5, 1):
            t = t0 + frac * (t1 - t0)
            draw.text((x0 + 4 + frac * (pw - 24) - 12, yb - 4), f'{t:.1f}s', fill=(90, 90, 90), font=small)
    image.save(out)
    return out


def reference_pack(ref_paths, times, out_dir, max_cells=48):
    """Pictures of the target alone, given to every condition at the start: a dense filmstrip and motion curves."""
    frames = [load_rgb(p, True) for p in ref_paths]
    idx = sample(len(times), max_cells)
    strips = filmstrip([('target', [frames[i] for i in idx])], [times[i] for i in idx], out_dir / 'ref_strip.png', max_cells=24)
    colours = palette(frames)
    curves = motion_curves(times, colours, tracks(frames, colours), None, out_dir / 'ref_curves.png')
    return strips + [curves], len(idx)
