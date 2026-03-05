# backend/app/core/logging.py
import logging

import logfire

from app.core.config import settings


class EndpointFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().find("/health") == -1


def setup_logging():
    """
    Configures Pydantic Logfire for the application and sets up Uvicorn logging rules.
    This should be called once at application startup.
    """
    logging.getLogger("uvicorn.access").addFilter(EndpointFilter())

    if settings.LOGFIRE_TOKEN:
        logfire.configure(
            token=settings.LOGFIRE_TOKEN,
            service_name=settings.PROJECT_NAME,
            environment=settings.ENVIRONMENT,
            console=settings.CONSOLE_LOG,
        )
        print("✅ Logfire configured successfully (Console output silenced).")

        # 🔥 FIX: Target specific business logic modules instead of the whole "app" folder.
        # This completely stops the middleware from generating empty "auto-tracing" spans!
        logfire.install_auto_tracing(
            modules=["app.api", "app.services", "app.repositories"],
            min_duration=0,
            check_imported_modules="ignore",
        )

        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO)

        if not any(
            isinstance(h, logfire.LogfireLoggingHandler) for h in root_logger.handlers
        ):
            root_logger.addHandler(logfire.LogfireLoggingHandler())
            print("✅ Logfire handler attached to root logger.")

    else:
        print("⚠️ LOGFIRE_TOKEN not set. Logging will be local only.")
        logging.basicConfig(level=logging.INFO)
