"""Start the service with the host and port from the settings:  python -m app

SERVICE_HOST and SERVICE_PORT come from the environment or .env (default 127.0.0.1:8006).
"""

import uvicorn

from app.core.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.service_host,
        port=settings.service_port,
        log_level=settings.log_level.lower(),
        # Uvicorn's own server header would advertise the server software; it adds nothing.
        server_header=False,
    )


if __name__ == "__main__":
    main()
