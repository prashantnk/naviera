import logging

import logfire
from app.core.config import settings


def setup_logging():
    """
    Configures Pydantic Logfire for the application.
    This should be called once at application startup.
    """
    if settings.LOGFIRE_TOKEN:
        logfire.configure(
            token=settings.LOGFIRE_TOKEN,
            service_name=settings.PROJECT_NAME,
        )
        print("✅ Logfire configured successfully.")

        # --- FIX 1: Suppress the warning ---
        logfire.install_auto_tracing(
            modules=["app"], min_duration=0, check_imported_modules="ignore"
        )

        # --- FIX 2: Force-attach the handler ---
        # Uvicorn sets up logging before we do, so basicConfig() is ignored.
        # We must manually add the Logfire handler to the root logger.
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        # Prevent adding the handler multiple times during reloads
        if not any(
            isinstance(h, logfire.LogfireLoggingHandler) for h in root_logger.handlers
        ):
            root_logger.addHandler(logfire.LogfireLoggingHandler())
            print("✅ Logfire handler attached to root logger.")

    else:
        print("⚠️ LOGFIRE_TOKEN not set. Logging will be local only.")
        logging.basicConfig(level=logging.INFO)


