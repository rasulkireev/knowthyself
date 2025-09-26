import structlog


def get_knowthyself_logger(name):
    """This will add a `knowthyself` prefix to logger for easy configuration."""

    return structlog.get_logger(
        f"knowthyself.{name}",
        project="knowthyself"
    )
