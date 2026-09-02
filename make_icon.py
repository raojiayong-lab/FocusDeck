# -*- coding: utf-8 -*-
"""生成 FocusDeck 图标（番茄 + 绿叶），输出 icon.ico（多尺寸）"""
import math
import os

from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icon.ico')
SIZE = 256


def rounded_mask(size, radius_ratio=0.22):
    m = Image.new('L', (size, size), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * radius_ratio), fill=255)
    return m


def make(size):
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # 背景：深色圆角块
    d.rounded_rectangle([0, 0, size - 1, size - 1],
                        radius=int(size * 0.22), fill=(17, 20, 32, 255))

    # 外圈光晕
    cx = cy = size * 0.5
    r = size * 0.30
    for i in range(6, 0, -1):
        rr = r + i * size * 0.022
        a = int(38 / i) + 8
        d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr],
                  outline=(255, 107, 107, a), width=max(1, int(size * 0.012)))

    # 进度环（剩余约 1/4 未完成）
    box = [cx - r, cy - r, cx + r, cy + r]
    d.arc(box, start=-90, end=-90 + 360 * 0.74, fill=(255, 107, 107, 255),
          width=max(2, int(size * 0.075)))
    d.arc(box, start=-90 + 360 * 0.74, end=270, fill=(60, 66, 88, 255),
          width=max(2, int(size * 0.075)))

    # 番茄主体
    br = r * 0.60
    d.ellipse([cx - br, cy - br * 0.94, cx + br, cy + br * 0.94], fill=(255, 92, 92, 255))
    # 高光
    hl = br * 0.42
    d.ellipse([cx - br * 0.48, cy - br * 0.62, cx - br * 0.48 + hl, cy - br * 0.62 + hl * 0.8],
              fill=(255, 165, 160, 170))

    # 绿叶
    lr = br * 0.44
    ly = cy - br * 0.92
    d.polygon([(cx, ly - lr * 0.35),
               (cx + lr, ly - lr * 0.05),
               (cx + lr * 0.15, ly + lr * 0.72),
               (cx - lr * 0.9, ly + lr * 0.15)], fill=(52, 211, 153, 255))
    d.line([(cx - lr * 0.75, ly + lr * 0.2), (cx + lr * 0.35, ly - lr * 0.12)],
           fill=(24, 150, 108, 255), width=max(1, int(size * 0.014)))

    # 茎
    d.line([(cx, ly - lr * 0.1), (cx + size * 0.012, ly - lr * 0.85)],
           fill=(34, 160, 116, 255), width=max(1, int(size * 0.022)))

    # 圆角裁切
    img.putalpha(rounded_mask(size))
    return img


def main():
    sizes = [256, 128, 96, 64, 48, 40, 32, 24, 20, 16]
    frames = [make(s) for s in sizes]
    frames[0].save(OUT, format='ICO',
                   sizes=[(s, s) for s in sizes],
                   append_images=frames[1:])
    print('icon ->', OUT, os.path.getsize(OUT), 'bytes')


if __name__ == '__main__':
    main()
