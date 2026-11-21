# Vectorloom

Vectorloom is a declarative, reproducible SVG asset pipeline. It renders registered SVG assets with librsvg, generates multi-size PNGs and a manifest, validates dimensions and alpha geometry, and detects stale generated output without modifying it.

## Commands

```bash
vectorloom build                    # run generators and update output
vectorloom check                    # generate in a temporary directory and compare
vectorloom validate                 # validate committed output only
vectorloom build --config icons.json
```

The default configuration file is `vectorloom.json` in the project root.

## Configuration

```json
{
  "sizes": [16, 32, 64, 128, 256, 512],
  "output": "output",
  "renderer": "rsvg-convert",
  "forbiddenSvgText": ["var("],
  "generators": [
    {"command": ["python3", "generators/build.py"]}
  ],
  "fonts": [
    {"pattern": "DejaVu Sans:style=Bold", "file": "DejaVuSans-Bold.ttf"}
  ],
  "assets": [
    {
      "project": "brand",
      "name": "icon",
      "source": "projects/brand/icon.svg",
      "sources": [
        {"source": "projects/brand/icon-small.svg", "maxWidth": 32}
      ],
      "sizeMode": "square",
      "checks": {
        "width": 512,
        "transparentCorners": true,
        "alphaSamples": [{"x": 256, "y": 256, "value": 0}],
        "alphaSegments": [{
          "axis": "y",
          "position": 256,
          "start": 0,
          "end": 511,
          "threshold": 128,
          "segments": [[40, 180], [330, 470]],
          "tolerance": 1
        }]
      }
    }
  ]
}
```

If `fontconfigEnv` is set, Vectorloom reads that environment variable and uses its value as `FONTCONFIG_FILE`.

## Principles

- SVG or upstream geometry is the source of truth; PNG is always derived.
- Rendering fixes width only and derives height from the SVG viewBox.
- Assets may select an alternate SVG for bounded output sizes via `sources`.
- `check` has no output-directory side effects.
- Alpha checks are decoded directly from PNG; ImageMagick is not required.
- Project-specific generators and assertions are declared in configuration instead of hard-coded into the core.
