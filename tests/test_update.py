"""Testes do atualizador (sem internet: o GitHub e simulado)."""

import io
import json
import os
import sys
import tarfile
import tempfile
import unittest

SRC = os.path.join(os.path.dirname(__file__), "..", "src")
sys.path.insert(0, SRC)

from logimouse import __version__  # noqa: E402
from logimouse import config  # noqa: E402
from logimouse import update as U  # noqa: E402

RULE = open(os.path.join(os.path.dirname(__file__), "..", "data", "42-logimouse.rules"), "rb").read()


def make_tarball(version, top=None, extra=None, break_code=False, init_version=None, rule=RULE):
    """Monta um .tar.gz igual ao que o GitHub entrega para uma tag."""
    top = top or f"logimouse-{version}"
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        def add(name, data, kind=tarfile.REGTYPE):
            ti = tarfile.TarInfo(name)
            ti.type = kind
            ti.size = len(data) if kind == tarfile.REGTYPE else 0
            tar.addfile(ti, io.BytesIO(data) if kind == tarfile.REGTYPE else None)
        add(top, b"", tarfile.DIRTYPE)
        pkg = os.path.join(SRC, "logimouse")
        for fn in sorted(os.listdir(pkg)):
            if not fn.endswith(".py"):
                continue
            with open(os.path.join(pkg, fn), "rb") as fh:
                data = fh.read()
            if fn == "__init__.py":
                data = data.replace(f'__version__ = "{__version__}"'.encode(),
                                    f'__version__ = "{init_version or version}"'.encode())
            if break_code and fn == "hidpp.py":
                data += b"\ndef quebrado(:\n"
            add(f"{top}/src/logimouse/{fn}", data)
        if rule is not None:
            add(f"{top}/data/42-logimouse.rules", rule)
        add(f"{top}/README.md", b"leia-me")
        for name, data in (extra or {}).items():
            add(name, data)
    return buf.getvalue()


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.prefix = os.path.join(self.tmp.name, "share", "logimouse")
        os.makedirs(os.path.join(self.prefix, "logimouse"))
        with open(os.path.join(self.prefix, "logimouse", "__init__.py"), "w") as fh:
            fh.write('__version__ = "1.0.0"\n')
        with open(os.path.join(self.prefix, U.MARKER), "w") as fh:
            fh.write("ok\n")
        self.rule_path = os.path.join(self.tmp.name, "42-logimouse.rules")
        with open(self.rule_path, "wb") as fh:
            fh.write(RULE)
        self._saved = (U.prefix_dir, U.INSTALLED_RULE, U._get, os.environ.get("XDG_CONFIG_HOME"))
        U.prefix_dir = lambda: self.prefix
        U.INSTALLED_RULE = self.rule_path
        os.environ["XDG_CONFIG_HOME"] = os.path.join(self.tmp.name, "config")
        config.DRY_RUN = False

    def tearDown(self):
        U.prefix_dir, U.INSTALLED_RULE, U._get, cfg = self._saved
        if cfg is None:
            os.environ.pop("XDG_CONFIG_HOME", None)
        else:
            os.environ["XDG_CONFIG_HOME"] = cfg
        self.tmp.cleanup()

    def installed_version(self):
        with open(os.path.join(self.prefix, "logimouse", "__init__.py")) as fh:
            txt = fh.read()
        return txt.split('__version__ = "', 1)[1].split('"', 1)[0]

    def leftovers(self):
        return [n for n in os.listdir(self.prefix) if n.startswith(".atualizando-")]


class VersionTests(unittest.TestCase):
    def test_parse_and_compare(self):
        self.assertEqual(U.parse_version("v1.2.3"), (1, 2, 3))
        self.assertIsNone(U.parse_version("beta"))
        self.assertTrue(U.is_newer("v1.10.0", "1.9.9"))
        self.assertFalse(U.is_newer("v1.2.0", "1.2.0"))
        self.assertFalse(U.is_newer("nada", "1.0.0"))


class CheckTests(Sandbox):
    def test_latest_picks_highest_semver(self):
        tags = [{"name": "v1.2.0"}, {"name": "v1.10.0"}, {"name": "teste"}, {"name": "v1.9.3"}]
        U._get = lambda url, timeout=20: json.dumps(tags).encode()
        self.assertEqual(U.latest(), "v1.10.0")
        info = U.check()
        self.assertEqual(info["latest"], "1.10.0")
        self.assertTrue(info["newer"])

    def test_no_tags(self):
        U._get = lambda url, timeout=20: b"[]"
        self.assertEqual(U.check(), dict(current=__version__, latest=None, tag=None, newer=False))
        self.assertIn("Nenhuma", U.check_and_install()[0])


class InstallTests(Sandbox):
    def test_install_and_rollback(self):
        res = U.install("v9.0.0", data=make_tarball("9.0.0"))
        self.assertEqual(res, dict(version="9.0.0", needs_installer=False))
        self.assertEqual(self.installed_version(), "9.0.0")
        self.assertTrue(os.path.isfile(os.path.join(self.prefix, "logimouse", "tray.py")))
        self.assertTrue(os.path.isdir(os.path.join(self.prefix, "logimouse.anterior")))
        self.assertEqual(self.leftovers(), [])
        U.rollback()
        self.assertEqual(self.installed_version(), "1.0.0")

    def test_rule_change_asks_for_installer(self):
        res = U.install("v9.0.0", data=make_tarball("9.0.0", rule=RULE + b"# nova linha\n"))
        self.assertTrue(res["needs_installer"])

    def test_broken_code_keeps_old_version(self):
        with self.assertRaises(U.UpdateError):
            U.install("v9.0.0", data=make_tarball("9.0.0", break_code=True))
        self.assertEqual(self.installed_version(), "1.0.0")
        self.assertEqual(self.leftovers(), [])

    def test_wrong_version_in_package(self):
        with self.assertRaises(U.UpdateError):
            U.install("v9.0.0", data=make_tarball("9.0.0", init_version="8.0.0"))
        self.assertEqual(self.installed_version(), "1.0.0")

    def test_path_traversal_rejected(self):
        evil = make_tarball("9.0.0", extra={"logimouse-9.0.0/../../fora.txt": b"x"})
        with self.assertRaises(U.UpdateError):
            U.install("v9.0.0", data=evil)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "fora.txt")))
        self.assertEqual(self.installed_version(), "1.0.0")

    def test_corrupt_download(self):
        with self.assertRaises(U.UpdateError):
            U.install("v9.0.0", data=b"isto nao e um tar.gz")
        self.assertEqual(self.installed_version(), "1.0.0")

    def test_not_installed_by_installer(self):
        os.remove(os.path.join(self.prefix, U.MARKER))
        self.assertFalse(U.can_self_update())
        with self.assertRaises(U.UpdateError):
            U.install("v9.0.0", data=make_tarball("9.0.0"))

    def test_check_and_install_end_to_end(self):
        tarball = make_tarball("9.0.0")

        def fake_get(url, timeout=20):
            return json.dumps([{"name": "v9.0.0"}]).encode() if "api.github.com" in url else tarball
        U._get = fake_get
        msg, res = U.check_and_install()
        self.assertIn("para 9.0.0", msg)
        self.assertEqual(self.installed_version(), "9.0.0")
        self.assertEqual(config.get_option("updated_to"), "9.0.0")


if __name__ == "__main__":
    unittest.main()
