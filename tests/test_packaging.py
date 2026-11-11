import glob
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_all_modules_are_packaged():
    """Every mc3000_*.py must be listed in py-modules, otherwise the installed app fails to start."""
    toml = open(os.path.join(ROOT, "pyproject.toml"), encoding="utf-8").read()
    listed = set(re.findall(r'"([\w]+)"', re.search(r"py-modules\s*=\s*\[(.*?)\]", toml, re.S).group(1)))
    modules = {os.path.basename(p)[:-3] for p in glob.glob(os.path.join(ROOT, "mc3000_*.py"))}
    assert modules <= listed, f"missing in py-modules: {sorted(modules - listed)}"
