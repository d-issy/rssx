import logging
import os
from pathlib import Path

import uvicorn

from .app import create_app
from .config import Config


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = Config.load()
    if os.environ.get("RSSX_DEV"):
        pkg_dir = Path(__file__).resolve().parent
        uvicorn.run(
            "rssx.app:create_app",
            host=config.host,
            port=config.port,
            reload=True,
            reload_dirs=[str(pkg_dir)],
            reload_includes=["*.py", "*.html", "*.css", "*.js"],
            factory=True,
            log_level="info",
        )
    else:
        app = create_app(config)
        uvicorn.run(app, host=config.host, port=config.port, log_level="info")


if __name__ == "__main__":
    main()
