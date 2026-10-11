import argparse
import logging
import os
from pathlib import Path

from .build import SalesFeed, build


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static HSB economy API.")
    parser.add_argument("--out", type=Path, default=Path("site"), help="Directory to write the site to")
    parser.add_argument("--state", type=Path, default=Path("state/state.json.gz"), help="Pipeline state file")
    parser.add_argument(
        "--public-url",
        default=os.getenv("HSB_PUBLIC_URL"),
        help="Base URL of the deployed site, used to recover state when no local copy exists",
    )
    parser.add_argument(
        "--sales-url",
        default=os.getenv("HSB_SALES_URL"),
        help="Base URL of the sales feed Worker; without it, auctions_ended is sampled directly",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    feed = None
    if args.sales_url:
        # The token is only read from the environment so it never appears in process listings.
        token = os.getenv("HSB_SALES_TOKEN")
        if not token:
            parser.error("HSB_SALES_TOKEN must be set when a sales feed URL is given")
        feed = SalesFeed(args.sales_url, token)
    build(args.out, args.state, args.public_url, feed)


if __name__ == "__main__":
    main()
