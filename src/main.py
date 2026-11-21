"""OrbitWhisper entrypoint.

This module keeps runtime wiring minimal for the scaffold stage.
"""

from __future__ import annotations

import logging


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
logger = logging.getLogger("orbitwhisper")


def main() -> None:
    logger.info("OrbitWhisper scaffold is ready. Integrate pipeline scheduling as next step.")


if __name__ == "__main__":
    main()
