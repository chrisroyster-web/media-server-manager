import main as appmod


def test_app_builds_and_maps(app):
    assert app.winfo_exists()
    assert app.sidebar.winfo_ismapped()


def test_every_tab_selects_without_error(app):
    """Codifies the manual "headless walk" this app's been regression-
    tested with by hand all session: select every tab in turn and make
    sure nothing raises. Catches import-order bugs, stale attribute
    references after a tab merge/rename, etc."""
    errors = []
    for idx, name in sorted(appmod._TAB_NAMES.items()):
        try:
            app.tabs.select(idx)
            app.update()
        except Exception as e:
            errors.append((idx, name, e))
    assert not errors, "\n".join(
        f"tab {idx} ({name}): {e!r}" for idx, name, e in errors)
