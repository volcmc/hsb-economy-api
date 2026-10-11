import argparse
import logging
import os
from pathlib import Path

from .build import build


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static HSB economy API.")
    parser.add_argument("--out", type=Path, default=Path("site"), help="Directory to write the site to")
    parser.add_argument("--state", type=Path, default=Path("state/state.json.gz"), help="Pipeline state file")
    parser.add_argument(
        "--public-url",
        default=os.getenv("HSB_PUBLIC_URL"),
        help="Base URL of the deployed site, used to recover state when no local copy exists",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    build(args.out, args.state, args.public_url)


if __name__ == "__main__":
    main()
