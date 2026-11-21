from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import tempfile
import zlib
from pathlib import Path
from typing import Any


class VectorloomError(RuntimeError):
    """A configuration, generation, rendering, or validation failure."""


def require_executable(name: str) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise VectorloomError(f"Required executable not found: {name}")
    return executable


def load_config(root: Path, config_name: str) -> dict[str, Any]:
    path = root / config_name
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise VectorloomError(f"Cannot read {path}: {error}") from error
    if not isinstance(config.get("sizes"), list) or not config["sizes"]:
        raise VectorloomError("Config requires a non-empty sizes array")
    if not isinstance(config.get("assets"), list):
        raise VectorloomError("Config requires an assets array")
    return config


def environment(config: dict[str, Any]) -> dict[str, str]:
    result = os.environ.copy()
    fontconfig_env = config.get("fontconfigEnv")
    if fontconfig_env:
        value = result.get(fontconfig_env)
        if not value:
            raise VectorloomError(
                f"Required environment variable is unset: {fontconfig_env}"
            )
        result["FONTCONFIG_FILE"] = value
    return result


def run_generators(
    root: Path, config: dict[str, Any], env: dict[str, str], *, check: bool
) -> None:
    for generator in config.get("generators", []):
        command = generator.get("checkCommand" if check else "command")
        if command is None and check:
            command = generator.get("command")
        if not isinstance(command, list) or not command:
            raise VectorloomError("Every generator requires a non-empty command array")
        subprocess.run([str(part) for part in command], cwd=root, env=env, check=True)


def assert_fonts(config: dict[str, Any], env: dict[str, str]) -> None:
    fonts = config.get("fonts", [])
    if not fonts:
        return
    fc_match = require_executable("fc-match")
    for font in fonts:
        actual = subprocess.check_output(
            [fc_match, "-f", "%{file}\n", font["pattern"]],
            text=True,
            env=env,
        ).strip()
        if Path(actual).name != font["file"]:
            raise VectorloomError(
                f"Font {font['pattern']!r} resolved to {actual}, expected {font['file']}"
            )


def source_for_width(root: Path, asset: dict[str, Any], width: int) -> Path:
    for candidate in asset.get("sources", []):
        minimum = candidate.get("minWidth", 0)
        maximum = candidate.get("maxWidth", width)
        if minimum <= width <= maximum:
            return root / candidate["source"]
    return root / asset["source"]


def render(
    root: Path, output: Path, config: dict[str, Any], env: dict[str, str]
) -> None:
    renderer = require_executable(config.get("renderer", "rsvg-convert"))
    manifest: dict[str, Any] = {"projects": {}}
    output.mkdir(parents=True, exist_ok=True)
    for asset in config["assets"]:
        source = root / asset["source"]
        project, name = asset["project"], asset["name"]
        destination = output / project
        destination.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination / f"{name}.svg")
        pngs = []
        for width in config["sizes"]:
            filename = f"{name}-{width}.png"
            render_source = source_for_width(root, asset, width)
            subprocess.run(
                [
                    renderer,
                    "-w",
                    str(width),
                    "-o",
                    str(destination / filename),
                    str(render_source),
                ],
                env=env,
                check=True,
            )
            pngs.append(filename)
        projects = manifest["projects"]
        entry = projects.setdefault(project, {"assets": {}})
        entry["assets"][name] = {"svg": f"{name}.svg", "png": pngs}
        print(f"  {project}/{name}: {len(pngs)} PNGs")
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def png_rgba(path: Path) -> tuple[int, int, bytes]:
    data = path.read_bytes()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise VectorloomError(f"Invalid PNG signature: {path}")
    position = 8
    width = height = color_type = bit_depth = 0
    compressed = bytearray()
    while position < len(data):
        length = struct.unpack(">I", data[position : position + 4])[0]
        kind = data[position + 4 : position + 8]
        payload = data[position + 8 : position + 8 + length]
        position += 12 + length
        if kind == b"IHDR":
            width, height, bit_depth, color_type = struct.unpack(">IIBB", payload[:10])
        elif kind == b"IDAT":
            compressed.extend(payload)
        elif kind == b"IEND":
            break
    if bit_depth != 8 or color_type not in (4, 6):
        raise VectorloomError(
            f"Only 8-bit grayscale+alpha/RGBA PNG is supported: {path}"
        )
    channels = 2 if color_type == 4 else 4
    stride = width * channels
    raw = zlib.decompress(compressed)
    rows: list[bytearray] = []
    offset = 0
    previous = bytearray(stride)
    for _ in range(height):
        filter_type = raw[offset]
        current = bytearray(raw[offset + 1 : offset + 1 + stride])
        offset += stride + 1
        for index in range(stride):
            left = current[index - channels] if index >= channels else 0
            up = previous[index]
            upper_left = previous[index - channels] if index >= channels else 0
            if filter_type == 1:
                current[index] = (current[index] + left) & 255
            elif filter_type == 2:
                current[index] = (current[index] + up) & 255
            elif filter_type == 3:
                current[index] = (current[index] + ((left + up) // 2)) & 255
            elif filter_type == 4:
                estimate = left + up - upper_left
                distances = (
                    abs(estimate - left),
                    abs(estimate - up),
                    abs(estimate - upper_left),
                )
                predictor = (left, up, upper_left)[distances.index(min(distances))]
                current[index] = (current[index] + predictor) & 255
            elif filter_type != 0:
                raise VectorloomError(f"Unsupported PNG filter {filter_type}: {path}")
        rows.append(current)
        previous = current
    rgba = bytearray(width * height * 4)
    for y, row in enumerate(rows):
        for x in range(width):
            source = x * channels
            target = (y * width + x) * 4
            if channels == 4:
                rgba[target : target + 4] = row[source : source + 4]
            else:
                gray, alpha = row[source : source + 2]
                rgba[target : target + 4] = bytes((gray, gray, gray, alpha))
    return width, height, bytes(rgba)


def alpha_segments(
    alpha: bytes,
    width: int,
    axis: str,
    position: int,
    start: int,
    end: int,
    threshold: int,
) -> list[list[int]]:
    segments: list[list[int]] = []
    segment_start: int | None = None
    for coordinate in range(start, end + 1):
        index = (
            (coordinate * width + position)
            if axis == "y"
            else (position * width + coordinate)
        )
        opaque = alpha[index] >= threshold
        if opaque and segment_start is None:
            segment_start = coordinate
        elif not opaque and segment_start is not None:
            segments.append([segment_start, coordinate - 1])
            segment_start = None
    if segment_start is not None:
        segments.append([segment_start, end])
    return segments


def validate(
    root: Path, output: Path, config: dict[str, Any], env: dict[str, str]
) -> None:
    assert_fonts(config, env)
    forbidden = config.get("forbiddenSvgText", [])
    expected_assets: set[tuple[str, str]] = set()
    for asset in config["assets"]:
        source = root / asset["source"]
        sources = [source] + [
            root / item["source"] for item in asset.get("sources", [])
        ]
        for checked_source in sources:
            text = checked_source.read_text(encoding="utf-8")
            for token in forbidden:
                if token in text:
                    raise VectorloomError(
                        f"Forbidden SVG text {token!r} in {checked_source}"
                    )
        project, name = asset["project"], asset["name"]
        expected_assets.add((project, name))
        for requested_width in config["sizes"]:
            path = output / project / f"{name}-{requested_width}.png"
            width, height, _ = png_rgba(path)
            if width != requested_width:
                raise VectorloomError(f"Wrong width for {path}: {width}")
            if asset.get("sizeMode", "square") == "square" and height != width:
                raise VectorloomError(f"Expected square PNG: {path}")
        checks = asset.get("checks", {})
        check_width = checks.get("width", max(config["sizes"]))
        path = output / project / f"{name}-{check_width}.png"
        width, height, rgba = png_rgba(path)
        alpha = rgba[3::4]
        if checks.get("transparentCorners"):
            corners = (
                alpha[0],
                alpha[width - 1],
                alpha[(height - 1) * width],
                alpha[-1],
            )
            if any(corners):
                raise VectorloomError(f"Opaque corners in {path}: {corners}")
        for sample in checks.get("alphaSamples", []):
            actual = alpha[sample["y"] * width + sample["x"]]
            tolerance = sample.get("tolerance", 0)
            if abs(actual - sample["value"]) > tolerance:
                raise VectorloomError(
                    f"Alpha sample failed in {path}: {sample}, got {actual}"
                )
        for scan in checks.get("alphaSegments", []):
            actual = alpha_segments(
                alpha,
                width,
                scan["axis"],
                scan["position"],
                scan["start"],
                scan["end"],
                scan.get("threshold", 128),
            )
            expected = scan["segments"]
            tolerance = scan.get("tolerance", 0)
            if len(actual) != len(expected) or any(
                abs(value - reference) > tolerance
                for segment, expected_segment in zip(actual, expected, strict=True)
                for value, reference in zip(segment, expected_segment, strict=True)
            ):
                raise VectorloomError(
                    f"Alpha segments failed in {path}: {actual}, expected {expected}"
                )
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    actual_assets = {
        (project, name)
        for project, entry in manifest["projects"].items()
        for name in entry["assets"]
    }
    if actual_assets != expected_assets:
        raise VectorloomError(
            f"Manifest assets differ: {actual_assets} != {expected_assets}"
        )


def files_equal(left: Path, right: Path) -> bool:
    left_files = {path.relative_to(left) for path in left.rglob("*") if path.is_file()}
    right_files = {
        path.relative_to(right) for path in right.rglob("*") if path.is_file()
    }
    return left_files == right_files and all(
        (left / path).read_bytes() == (right / path).read_bytes() for path in left_files
    )


def build(root: Path, config_name: str, *, check: bool) -> None:
    config = load_config(root, config_name)
    env = environment(config)
    assert_fonts(config, env)
    output = root / config.get("output", "output")
    if check:
        with tempfile.TemporaryDirectory() as temporary:
            temp_root = Path(temporary)
            run_generators(root, config, env, check=True)
            render(root, temp_root, config, env)
            validate(root, temp_root, config, env)
            if not files_equal(temp_root, output):
                raise VectorloomError(f"Generated output is stale: {output}")
    else:
        run_generators(root, config, env, check=False)
        render(root, output, config, env)
        validate(root, output, config, env)
