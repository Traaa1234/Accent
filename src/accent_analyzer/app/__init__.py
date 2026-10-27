"""Local web app (Record, Results, Progress, Practice, Settings)."""


def create_app(*args, **kwargs):
    from accent_analyzer.app.server import create_app as _create

    return _create(*args, **kwargs)


__all__ = ["create_app"]
