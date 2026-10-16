"""Tests for render_lineage.py. Stdlib only: ``python3 -m unittest discover tests``."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "render_lineage.py"
FIXTURE = ROOT / "tests" / "fixtures" / "jaffle_shop"


def run(*args: str) -> tuple[int, dict]:
    done = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                          text=True, timeout=60, check=False)
    return done.returncode, json.loads(done.stdout.strip().splitlines()[-1])


def page_data(path: Path) -> dict:
    found = re.search(r'id="data">(.*?)</script>', path.read_text(encoding="utf-8"), re.S)
    return json.loads(found.group(1))


class RenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.project = self.tmp / "jaffle_shop"
        shutil.copytree(FIXTURE, self.project)
        self.out = self.tmp / "page.html"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp)

    def render(self) -> tuple[int, dict]:
        return run("render", "--project", str(self.project), "--out", str(self.out))

    def test_renders_every_node_into_its_layer(self) -> None:
        code, result = self.render()
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "rendered")
        layers = {n["name"]: n["layer"] for n in page_data(self.out)["nodes"]}
        self.assertEqual(layers, {
            "jaffle.customers": "source", "jaffle.orders": "source",
            "raw_payments": "source", "orders_snapshot": "snapshots",
            "stg_customers": "staging", "stg_orders": "staging",
            "int_order_totals": "intermediate", "fct_orders": "marts",
            "dim_customers": "marts", "customer_report": "reporting",
        })
        self.assertEqual(result["edge_count"], 9)

    def test_tests_attach_to_the_models_they_guard(self) -> None:
        self.render()
        tests = {n["name"]: [t["n"] for t in n["tests"]] for n in page_data(self.out)["nodes"]}
        self.assertEqual(sorted(tests["fct_orders"]), ["assert_fct_orders_positive", "unique"])
        self.assertEqual(tests["stg_orders"], ["relationships"])

    def test_page_is_deterministic(self) -> None:
        _, first = self.render()
        _, second = self.render()
        self.assertEqual(first["sha256"], second["sha256"])

    def test_record_makes_the_next_render_unchanged(self) -> None:
        _, first = self.render()
        self.assertFalse(first["unchanged"])
        code, _ = run("record", "--project", str(self.project),
                      "--url", "https://claude.ai/artifact/example", "--sha256", first["sha256"])
        self.assertEqual(code, 0)
        _, second = self.render()
        self.assertTrue(second["unchanged"])
        self.assertEqual(second["artifact_url"], "https://claude.ai/artifact/example")

    def test_missing_manifest_exits_3(self) -> None:
        (self.project / "target" / "manifest.json").unlink()
        code, result = self.render()
        self.assertEqual((code, result["status"]), (3, "no_manifest"))

    def test_not_a_dbt_project_exits_2(self) -> None:
        (self.project / "dbt_project.yml").unlink()
        code, result = self.render()
        self.assertEqual((code, result["status"]), (2, "usage"))

    def test_config_sets_title_and_warns_on_unknown_source(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        (self.project / "lineage.yml").write_text(
            "title: Jaffle Shop\npartition_name: Region\n"
            "partitions:\n  - label: EU\n    sources: [jaffle, nowhere]\n", encoding="utf-8")
        code, result = self.render()
        self.assertEqual(code, 0)
        self.assertEqual(result["title"], "Jaffle Shop")
        self.assertEqual(result["warnings"], ["declared source nowhere is not in the manifest"])
        self.assertEqual(page_data(self.out)["filter_name"], "Region")

    def test_unknown_config_key_is_invalid(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        (self.project / "lineage.yml").write_text("titel: typo\n", encoding="utf-8")
        code, result = self.render()
        self.assertEqual((code, result["status"]), (5, "invalid"))

    def set_tags(self, uid: str, tags: list) -> None:
        manifest_path = self.project / "target" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["nodes"][uid]["tags"] = tags
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def test_a_tag_beats_the_name_and_folder(self) -> None:
        # customer_report sits in models/reporting/, but is tagged as a mart.
        self.set_tags("model.j.customer_report", ["nightly", "Marts"])
        self.render()
        node = {n["name"]: n for n in page_data(self.out)["nodes"]}["customer_report"]
        self.assertEqual((node["layer"], node["kind"]), ("marts", "mart"))

    def test_a_folder_wide_tag_keeps_the_prefix_kind(self) -> None:
        # +tags: ["marts"] on the whole folder sets the column; fct_ still says fact.
        self.set_tags("model.j.fct_orders", ["marts"])
        self.set_tags("model.j.dim_customers", ["marts"])
        self.render()
        kinds = {n["name"]: (n["layer"], n["kind"]) for n in page_data(self.out)["nodes"]}
        self.assertEqual(kinds["fct_orders"], ("marts", "fct"))
        self.assertEqual(kinds["dim_customers"], ("marts", "dim"))

    def test_config_rules_can_match_on_tags_alone(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        self.set_tags("model.j.int_order_totals", ["gold"])
        (self.project / "lineage.yml").write_text(
            "layers:\n  - {id: silver, label: Silver}\n  - {id: gold, label: Gold}\n"
            "rules:\n  - {kind: gold, label: Gold tables, layer: gold, tags: gold}\n"
            "  - {kind: silver, layer: silver, prefixes: [stg_]}\n", encoding="utf-8")
        code, _ = self.render()
        self.assertEqual(code, 0)
        layers = {n["name"]: n["layer"] for n in page_data(self.out)["nodes"]}
        self.assertEqual(layers["int_order_totals"], "gold")
        self.assertEqual(layers["stg_orders"], "silver")
        self.assertEqual(layers["fct_orders"], "other")

    def test_a_rule_with_an_unknown_key_is_invalid(self) -> None:
        try:
            import yaml  # noqa: F401
        except ImportError:
            self.skipTest("PyYAML not installed")
        (self.project / "lineage.yml").write_text(
            "rules:\n  - {kind: x, layer: other, tag: [x]}\n", encoding="utf-8")
        code, result = self.render()
        self.assertEqual((code, result["status"]), (5, "invalid"))
        self.assertIn("tag", result["detail"])

    def test_code_cannot_break_out_of_the_data_script(self) -> None:
        manifest_path = self.project / "target" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["nodes"]["model.j.fct_orders"]["raw_code"] = "select '</script><b>x</b>'"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        self.render()
        html = self.out.read_text(encoding="utf-8")
        self.assertEqual(html.count("</script>"), html.count("<script"))


if __name__ == "__main__":
    unittest.main()
