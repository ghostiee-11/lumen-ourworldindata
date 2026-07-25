"""Console entry point: ``lumen-owid``."""
from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    """Serve the Our World In Data explorer."""
    import panel as pn

    parser = argparse.ArgumentParser(description="Chat with Our World In Data.")
    parser.add_argument("--port", type=int, default=5006)
    parser.add_argument("--show", action="store_true", help="Open a browser window")
    args = parser.parse_args()

    pn.serve(
        str(Path(__file__).parent / "app.py"),
        port=args.port,
        show=args.show,
        autoreload=False,
    )


if __name__ == "__main__":
    main()
