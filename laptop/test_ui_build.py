"""The operator and control pages: TypeScript sources, the JavaScript built from them, and the
files each page loads."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server

LAPTOP = Path(__file__).resolve().parent
NODE = shutil.which("node")
needs_node = pytest.mark.skipif(NODE is None, reason="Node is not installed")
PAGES_WITH_SCRIPTS = ["autonomous.html", "control.html"]


def node(*args, timeout=60):
    return subprocess.run(
        [NODE, "--disable-warning=ExperimentalWarning", *args],
        cwd=LAPTOP, capture_output=True, text=True, timeout=timeout,
    )


def sources():
    return sorted(p for p in LAPTOP.glob("*.ts") if not p.name.endswith(".test.ts"))


def local_assets(html_name):
    html = (LAPTOP / html_name).read_text(encoding="utf-8")
    found = re.findall(r'(?:src|href)="([^"#]+)"', html)
    return [a.split("?")[0] for a in found if not a.startswith(("http", "mailto", "/"))]


@needs_node
def test_every_built_javascript_file_matches_its_typescript_source():
    result = node("build.mjs", "--check")

    assert result.returncode == 0, result.stderr


def test_every_typescript_source_has_its_built_file():
    for source in sources():
        assert source.with_suffix(".js").exists(), f"run node build.mjs: {source.name} has no .js"


@needs_node
def test_every_built_file_is_valid_javascript():
    for source in sources():
        result = node("--check", str(source.with_suffix(".js")))
        assert result.returncode == 0, f"{source.with_suffix('.js').name}: {result.stderr}"


@needs_node
def test_the_built_files_hold_no_type_syntax():
    for source in sources():
        text = source.with_suffix(".js").read_text(encoding="utf-8")
        assert "interface " not in text and ": string" not in text and "import type" not in text, source.name


@needs_node
def test_the_logic_tests_pass_in_node():
    result = node("--test", "ui_logic.test.ts", timeout=120)

    assert result.returncode == 0, result.stdout[-1500:] + result.stderr[-500:]


@pytest.mark.parametrize("page", PAGES_WITH_SCRIPTS)
def test_every_file_a_page_loads_is_served_by_the_server(page):
    client = TestClient(server.create_app(source=None))

    for asset in local_assets(page):
        assert client.get(f"/{asset}").status_code == 200, f"{page} loads {asset} but the server will not serve it"


@pytest.mark.parametrize("page", PAGES_WITH_SCRIPTS)
def test_pages_load_their_script_as_a_module_because_it_imports(page):
    html = (LAPTOP / page).read_text(encoding="utf-8")

    assert re.search(r'<script type="module" src="(operator|control)\.js', html)


def test_the_typescript_sources_themselves_are_not_served():
    client = TestClient(server.create_app(source=None))

    for source in sources():
        assert client.get(f"/{source.name}").status_code == 404
    assert client.get("/build.mjs").status_code == 404
    assert client.get("/package.json").status_code == 404


def test_the_pages_only_use_ids_their_scripts_look_for():
    for page, script in (("autonomous.html", "operator.ts"), ("control.html", "control.ts")):
        html = (LAPTOP / page).read_text(encoding="utf-8")
        wanted = set(re.findall(r'\$<[^>]+>\("([\w-]+)"\)', (LAPTOP / script).read_text(encoding="utf-8")))
        wanted |= set(re.findall(r'\$\("([\w-]+)"\)', (LAPTOP / script).read_text(encoding="utf-8")))
        present = set(re.findall(r'id="([\w-]+)"', html))
        assert wanted <= present, f"{script} looks for {sorted(wanted - present)} but {page} has no such id"
