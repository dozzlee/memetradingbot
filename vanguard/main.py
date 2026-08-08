"""Entrypoint: serves the dashboard + control API. The monitor loop itself
is started/stopped from the dashboard (POST /api/control/start|stop), not
automatically on boot — so you can add wallets before it goes live."""
import logging

import uvicorn

logging.basicConfig(level=logging.INFO)

if __name__ == "__main__":
    uvicorn.run("vanguard.web.app:app", host="127.0.0.1", port=8000, log_level="info")
