"""Guard the `config` name against the package/module collision.

`config.py` (ConfigurationManager) and the `config/` data directory share a
name. Python resolves a directory holding `__init__.py` ahead of a sibling
`.py` file, so adding `config/__init__.py` silently turns `config/` into a
regular package and makes `main.py`'s `from config import ConfigurationManager`
raise ImportError. That happened in b3bb25e and went unnoticed for five months
because nothing imports the package and only bot mode reaches the line.

A bare `config/` directory with no `__init__.py` is safe: `config.py` still
wins, and the directory is only ever used for file paths (`config/cities`,
`config/credentials.env`).
"""
import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_config_dir_is_not_a_python_package():
    """config/ must stay a plain data directory, not a package."""
    init_py = os.path.join(ROOT, "config", "__init__.py")
    assert not os.path.exists(init_py), (
        "config/__init__.py shadows config.py and breaks "
        "`from config import ConfigurationManager` in main.py. Delete it."
    )


def test_config_name_resolves_to_config_py():
    """The import system must pick config.py for the name `config`."""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    spec = importlib.util.find_spec("config")
    assert spec is not None, "no module named 'config' on the path"
    assert spec.origin == os.path.join(ROOT, "config.py"), (
        f"`config` resolved to {spec.origin}, expected config.py"
    )


def test_configuration_manager_is_importable():
    """The exact import main.py:41 performs."""
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from config import ConfigurationManager

    assert isinstance(ConfigurationManager, type)


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"{name}: ok")
