"""Version string for generated scripts."""


def display_version():
    from utvfx.version import APP_NAME, VERSION
    return f"{APP_NAME} {VERSION}"
