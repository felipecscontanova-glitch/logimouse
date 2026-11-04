"""
Atualizacao automatica a partir das versoes publicadas no GitHub.

Uma versao e uma tag no formato vX.Y.Z. O atualizador baixa o .tar.gz da
tag, confere (versao certa, tudo compila e importa) e troca a pasta do
programa em ~/.local/share/logimouse, guardando a anterior para voltar se
algo der errado. Nao precisa de senha.
"""

import compileall
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request

from . import __version__
from . import config

REPO = "felipecscontanova-glitch/logimouse"
TAGS_URL = "https://api.github.com/repos/{repo}/tags?per_page=100"
TARBALL_URL = "https://codeload.github.com/{repo}/tar.gz/refs/tags/{tag}"
PAGE_URL = "https://github.com/{repo}"
MAX_DOWNLOAD = 20 * 1024 * 1024
MARKER = ".instalado"
INSTALLED_RULE = "/etc/udev/rules.d/42-logimouse.rules"
CHECK_EVERY = 24 * 3600


class UpdateError(Exception):
    pass


def repo():
    return config.get_option("update_repo") or REPO


def page_url():
    return PAGE_URL.format(repo=repo())


def parse_version(s):
    m = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)", (s or "").strip())
    return tuple(int(x) for x in m.groups()) if m else None


def is_newer(candidate, current=__version__):
    a, b = parse_version(candidate), parse_version(current)
    return a is not None and b is not None and a > b


def _get(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": f"logimouse/{__version__}",
        "Accept": "application/vnd.github+json",
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = r.read(MAX_DOWNLOAD + 1)
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise UpdateError("o GitHub limitou as consultas por agora; tente mais tarde") from e
        if e.code == 404:
            raise UpdateError("repositório ou versão não encontrados no GitHub") from e
        raise UpdateError(f"o GitHub respondeu {e.code}") from e
    except (urllib.error.URLError, OSError) as e:
        raise UpdateError("sem conexão com o GitHub") from e
    if len(data) > MAX_DOWNLOAD:
        raise UpdateError("download grande demais")
    return data


def latest():
    """Devolve a tag mais nova publicada (ex.: 'v1.2.0') ou None."""
    try:
        tags = json.loads(_get(TAGS_URL.format(repo=repo())).decode("utf-8"))
    except ValueError as e:
        raise UpdateError("resposta estranha do GitHub") from e
    best = None
    for t in tags if isinstance(tags, list) else []:
        name = t.get("name") if isinstance(t, dict) else None
        v = parse_version(name)
        if v and (best is None or v > best[0]):
            best = (v, name)
    return best[1] if best else None


def check():
    """Devolve dict(current, latest, tag, newer)."""
    tag = latest()
    return dict(current=__version__, latest=tag.lstrip("v") if tag else None,
                tag=tag, newer=bool(tag and is_newer(tag)))


# --------------------------------------------------------------------------
# Onde o programa esta instalado
# --------------------------------------------------------------------------
def package_dir():
    return os.path.dirname(os.path.abspath(__file__))


def prefix_dir():
    return os.path.dirname(package_dir())


def can_self_update():
    """So atualiza sozinho quando foi instalado pelo instalar.sh (nao num git clone)."""
    p = prefix_dir()
    return os.path.isfile(os.path.join(p, MARKER)) and os.access(p, os.W_OK)


def why_not_self_update():
    if not os.path.isfile(os.path.join(prefix_dir(), MARKER)):
        return "rodando direto do código-fonte: use git pull"
    return "sem permissão para gravar em " + prefix_dir()


# --------------------------------------------------------------------------
# Instalar
# --------------------------------------------------------------------------
def _safe_members(tar):
    """Arquivos do pacote: src/logimouse/** e data/42-logimouse.rules, sem truques de caminho."""
    names = tar.getnames()
    if not names:
        raise UpdateError("pacote vazio")
    top = names[0].split("/", 1)[0]
    pkg_prefix = f"{top}/src/logimouse/"
    rule_name = f"{top}/data/42-logimouse.rules"
    files, rule = {}, None
    for m in tar.getmembers():
        n = m.name
        if n.startswith("/") or ".." in n.split("/") or not (n == top or n.startswith(top + "/")):
            raise UpdateError(f"caminho suspeito no pacote: {n}")
        if m.isdir():
            continue
        if not m.isfile():
            if n.startswith(pkg_prefix):
                raise UpdateError(f"tipo de arquivo inesperado no pacote: {n}")
            continue
        if n.startswith(pkg_prefix):
            rel = n[len(pkg_prefix):]
            if rel and "__pycache__" not in rel.split("/"):
                files[rel] = m
        elif n == rule_name:
            rule = m
    if "__init__.py" not in files:
        raise UpdateError("pacote sem o programa")
    return files, rule


def _verify(staging_parent, expected):
    pkg = os.path.join(staging_parent, "logimouse")
    if not compileall.compile_dir(pkg, quiet=1, force=True):
        raise UpdateError("a versão nova tem arquivos com erro")
    probe = ("import logimouse, logimouse.hidpp, logimouse.config, logimouse.cli, "
             "logimouse.tray, logimouse.gui, logimouse.update; print(logimouse.__version__)")
    env = dict(os.environ, PYTHONPATH=staging_parent)
    try:
        out = subprocess.run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, %r); %s"
                              % (staging_parent, probe)],
                             env=env, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        raise UpdateError(f"não deu para testar a versão nova ({e})") from e
    if out.returncode != 0:
        raise UpdateError("a versão nova não abriu: " + (out.stderr.strip().splitlines() or ["?"])[-1])
    if out.stdout.strip() != expected:
        raise UpdateError(f"versão inesperada no pacote ({out.stdout.strip()} em vez de {expected})")


def install(tag, data=None):
    """Baixa e instala a tag. Devolve dict(version, needs_installer)."""
    if not can_self_update():
        raise UpdateError(why_not_self_update())
    expected = tag.lstrip("v")
    if parse_version(expected) is None:
        raise UpdateError(f"versão inválida: {tag}")
    if data is None:
        data = _get(TARBALL_URL.format(repo=repo(), tag=tag), timeout=60)

    prefix = prefix_dir()
    target = os.path.join(prefix, "logimouse")
    backup = os.path.join(prefix, "logimouse.anterior")
    work = tempfile.mkdtemp(prefix=".atualizando-", dir=prefix)
    try:
        try:
            tar = tarfile.open(fileobj=io.BytesIO(data), mode="r:gz")
        except (tarfile.TarError, OSError, EOFError) as e:
            raise UpdateError("o download veio corrompido") from e
        with tar:
            files, rule = _safe_members(tar)
            staging = os.path.join(work, "logimouse")
            for rel, m in files.items():
                dest = os.path.join(staging, *rel.split("/"))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                src = tar.extractfile(m)
                with open(dest, "wb") as fh:
                    shutil.copyfileobj(src, fh)
            rule_bytes = tar.extractfile(rule).read() if rule is not None else None
        _verify(work, expected)

        shutil.rmtree(backup, ignore_errors=True)
        if os.path.isdir(target):
            os.rename(target, backup)
        try:
            os.rename(staging, target)
        except OSError:
            if os.path.isdir(backup) and not os.path.exists(target):
                os.rename(backup, target)
            raise
    finally:
        shutil.rmtree(work, ignore_errors=True)

    needs_installer = False
    if rule_bytes is not None:
        try:
            with open(INSTALLED_RULE, "rb") as fh:
                needs_installer = fh.read() != rule_bytes
        except OSError:
            needs_installer = True
    config.set_option("updated_to", expected)
    return dict(version=expected, needs_installer=needs_installer)


def rollback():
    """Volta para a versao anterior guardada."""
    prefix = prefix_dir()
    target = os.path.join(prefix, "logimouse")
    backup = os.path.join(prefix, "logimouse.anterior")
    if not os.path.isdir(backup):
        raise UpdateError("não há versão anterior guardada")
    tmp = target + ".troca"
    shutil.rmtree(tmp, ignore_errors=True)
    os.rename(target, tmp)
    os.rename(backup, target)
    os.rename(tmp, backup)


def check_and_install():
    """Para o terminal e para a bandeja: devolve (mensagem, resultado_ou_None)."""
    info = check()
    if not info["tag"]:
        return "Nenhuma versão publicada no GitHub ainda.", None
    if not info["newer"]:
        return f"Você já está na versão mais nova ({info['current']}).", None
    res = install(info["tag"])
    msg = f"Atualizado de {info['current']} para {res['version']}."
    if res["needs_installer"]:
        msg += " Esta versão mudou a permissão de acesso ao mouse: rode o instalar.sh de novo."
    return msg, res
