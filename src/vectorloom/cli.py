import argparse
from pathlib import Path

from vectorloom.core import VectorloomError, build, environment, load_config, validate


def main() -> None:
    parser = argparse.ArgumentParser(prog="vectorloom")
    parser.add_argument("command", choices=("build", "check", "validate"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--config", default="vectorloom.json")
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if args.command in ("build", "check"):
            build(root, args.config, check=args.command == "check")
        else:
            config = load_config(root, args.config)
            validate(
                root,
                root / config.get("output", "output"),
                config,
                environment(config),
            )
    except (VectorloomError, OSError) as error:
        parser.exit(1, f"vectorloom: {error}\n")


if __name__ == "__main__":
    main()
