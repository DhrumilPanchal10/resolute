"""Smoke test: repo scaffold is importable."""


def test_packages_importable() -> None:
    import agentcore  # noqa: F401
    import resolute  # noqa: F401
