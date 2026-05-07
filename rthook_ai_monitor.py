# PyInstaller runtime hook (runs before app imports).
import os
import sys
import tempfile

if getattr(sys, "frozen", False):
    # comtypes (via uiautomation) uses %TEMP%\comtypes_cache\<exename>-<pyXY>.
    # Pre-create that folder so _find_gen_dir() skips makedirs(); WinError 183 can
    # occur if a file collides with that path or mkdir races.
    _tmp = tempfile.gettempdir()
    _parent = os.path.join(_tmp, "comtypes_cache")
    if os.path.exists(_parent) and not os.path.isdir(_parent):
        try:
            os.remove(_parent)
        except OSError:
            pass
    try:
        os.makedirs(_parent, exist_ok=True)
    except OSError:
        pass

    _base = os.path.splitext(os.path.basename(sys.executable))[0]
    _pymaj, _pymin = sys.version_info[:2]
    _gen = os.path.join(_parent, f"{_base}-{_pymaj}{_pymin}")
    if os.path.exists(_gen) and not os.path.isdir(_gen):
        try:
            os.remove(_gen)
        except OSError:
            pass
    try:
        os.makedirs(_gen, exist_ok=True)
    except OSError:
        pass

    mp = getattr(sys, "_MEIPASS", None)
    if mp and mp not in sys.path:
        sys.path.insert(0, mp)
