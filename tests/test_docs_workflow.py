"""Guard the documentation workflow.

The manual is published from ``docs/`` to GitHub Pages. A mistake in the
workflow is invisible until the deploy fails, so these checks pin the parts that
break silently: the strict build, the Pages permissions and the artifact name.
"""

import unittest
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "docs.yml"
CONFIG = REPO_ROOT / "mkdocs.yml"
REQUIREMENTS = REPO_ROOT / "requirements-docs.txt"

# The first major of each Pages action that runs on Node 24 (the runners removed
# Node 20 on 2026-09-23). upload-pages-artifact is a composite action, so it has
# no Node runtime of its own; its floor is simply the current major.
MINIMUM_MAJORS = {
    "actions/checkout": 5,
    "actions/setup-python": 6,
    "actions/configure-pages": 6,
    "actions/upload-pages-artifact": 5,
    "actions/deploy-pages": 5,
}


def load_workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def steps() -> list[dict]:
    return [step for job in load_workflow()["jobs"].values() for step in job["steps"]]


def run_commands() -> str:
    return "\n".join(step.get("run", "") for step in steps())


def step_named(name: str) -> dict:
    for step in steps():
        if step.get("name") == name:
            return step
    raise AssertionError(f"no step named {name!r} in {WORKFLOW.name}")


def uses_refs() -> list[str]:
    return [step["uses"] for step in steps() if "uses" in step]


def nav_entries(node) -> list[str]:
    """Collect every page path from the nested ``nav`` structure."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [page for value in node.values() for page in nav_entries(value)]
    if isinstance(node, list):
        return [page for value in node for page in nav_entries(value)]
    return []


class TestWorkflowTriggers(unittest.TestCase):
    def _triggers(self) -> dict:
        workflow = load_workflow()
        # PyYAML resolves the bare ``on`` key to True (YAML 1.1), so accept both.
        return workflow.get("on") or workflow[True]

    def test_it_deploys_only_from_main(self):
        push = self._triggers()["push"]
        self.assertEqual(push["branches"], ["main"])
        self.assertNotIn("tags", push)

    def test_it_can_be_run_manually(self):
        self.assertIn("workflow_dispatch", self._triggers())


class TestStrictBuild(unittest.TestCase):
    def test_the_build_runs_mkdocs_in_strict_mode(self):
        self.assertIn("mkdocs build --strict", run_commands())

    def test_mkdocs_config_is_also_strict(self):
        config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        self.assertIs(config["strict"], True)
        self.assertEqual(config["docs_dir"], "docs")

    def test_every_nav_page_exists(self):
        config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        for page in nav_entries(config["nav"]):
            with self.subTest(page=page):
                self.assertTrue((REPO_ROOT / "docs" / page).is_file(), page)


class TestPagesDeployment(unittest.TestCase):
    def _deploy_job(self) -> dict:
        workflow = load_workflow()
        return workflow["jobs"]["deploy"]

    def test_the_job_has_the_pages_permissions(self):
        permissions = self._deploy_job()["permissions"]
        self.assertEqual(permissions["pages"], "write")
        self.assertEqual(permissions["id-token"], "write")

    def test_the_workflow_itself_is_read_only(self):
        # The docs workflow never writes to the repository, unlike the release
        # workflows which need contents: write.
        self.assertEqual(load_workflow()["permissions"], {"contents": "read"})

    def test_it_declares_the_github_pages_environment(self):
        environment = self._deploy_job()["environment"]
        self.assertEqual(environment["name"], "github-pages")
        self.assertIn("page_url", environment["url"])

    def test_it_uploads_the_site_directory_under_the_default_name(self):
        upload = next(
            step for step in steps() if "upload-pages-artifact" in step.get("uses", "")
        )
        self.assertEqual(upload["with"]["path"], "site")
        # deploy-pages looks for an artifact literally named github-pages, so a
        # custom name would break the handoff.
        self.assertNotIn("name", upload["with"])


class TestActionsAreNode24(unittest.TestCase):
    def test_no_action_is_pinned_below_its_node24_major(self):
        for ref in uses_refs():
            name, _, version = ref.partition("@")
            major = version.lstrip("v").split(".")[0]
            with self.subTest(action=ref):
                self.assertIn(name, MINIMUM_MAJORS, "action is not audited")
                self.assertGreaterEqual(int(major), MINIMUM_MAJORS[name])


class TestDocumentationDependencies(unittest.TestCase):
    def test_the_docs_requirements_pin_mkdocs_material(self):
        self.assertTrue(REQUIREMENTS.is_file(), REQUIREMENTS)
        self.assertIn("mkdocs-material", REQUIREMENTS.read_text(encoding="utf-8"))

    def test_the_release_workflows_do_not_install_the_docs_requirements(self):
        # requirements.txt is bundled into the binaries; documentation packages
        # must not leak into them.
        for name in ("build-linux.yml", "build-windows.yml"):
            text = (WORKFLOW.parent / name).read_text(encoding="utf-8")
            with self.subTest(workflow=name):
                self.assertNotIn("requirements-docs.txt", text)


if __name__ == "__main__":
    unittest.main()
