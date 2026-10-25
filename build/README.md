# Profile README builder

The images in `assets/` are generated, not hand-edited. They use Vercel's
Geist design system: its color scales, type scale and grid, with Geist Sans
and Geist Mono embedded in every SVG.

To change any text, edit the `CONTENT`, `BATTERY`, `PALO` or `WEATHER` blocks
at the top of `build.py`, then rebuild:

```sh
pip install -r build/requirements.txt
python3 build/build.py
```

Each piece is written twice, `-light.svg` and `-dark.svg`. The README picks
one with `<picture>` based on the visitor's GitHub theme.

Text is measured with HarfBuzz against the real font files, so layout stays
exact after edits. If a line gets too long for its card, the build stops and
names the line.

Fonts: Geist Sans and Geist Mono, © 2023 Vercel in collaboration with
basement.studio, SIL Open Font License 1.1 (see `fonts/OFL.txt`).
