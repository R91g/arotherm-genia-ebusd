"""Unit tests for schema integrity, manifest, translations, and services validation."""

import json
import os
import re
import struct
import sys
import unittest
from typing import Any

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
import setup_mocks  # noqa: F401

from custom_components.arotherm_genia_ebusd.const import (
    DOMAIN,
    SERVICE_CANCEL_HOLIDAY_MODE,
    SERVICE_FORCE_DHW_BOOST,
    SERVICE_SET_HOLIDAY_MODE,
    SERVICE_SET_WEEKLY_TIMER,
)


class TestSchemaIntegrity(unittest.TestCase):
    """Test manifest.json, hacs.json, translation files, and services.yaml."""

    def setUp(self) -> None:
        """Set up file paths."""
        self.root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.component_dir = os.path.join(
            self.root_dir, "custom_components", "arotherm_genia_ebusd"
        )
        self.manifest_path = os.path.join(self.component_dir, "manifest.json")
        self.hacs_path = os.path.join(self.root_dir, "hacs.json")
        self.strings_path = os.path.join(self.component_dir, "strings.json")
        self.icons_path = os.path.join(self.component_dir, "icons.json")
        self.es_path = os.path.join(self.component_dir, "translations", "es.json")
        self.en_path = os.path.join(self.component_dir, "translations", "en.json")
        self.services_path = os.path.join(self.component_dir, "services.yaml")

    def test_manifest_schema(self) -> None:
        """Verify manifest.json adheres to official Home Assistant requirements."""
        self.assertTrue(os.path.exists(self.manifest_path), "manifest.json missing")
        with open(self.manifest_path, "r", encoding="utf-8") as fp:
            manifest = json.load(fp)

        # Mandatory Hassfest fields
        required_keys = [
            "domain",
            "name",
            "codeowners",
            "config_flow",
            "documentation",
            "iot_class",
            "issue_tracker",
            "version",
        ]
        for key in required_keys:
            self.assertIn(key, manifest, f"Missing key in manifest.json: {key}")

        self.assertEqual(manifest["domain"], DOMAIN)
        self.assertEqual(manifest["domain"], "arotherm_genia_ebusd")
        self.assertTrue(manifest["config_flow"])
        self.assertIn(
            manifest["iot_class"],
            ["local_push", "local_polling", "cloud_push", "cloud_polling"],
        )
        self.assertTrue(isinstance(manifest["codeowners"], list))
        self.assertGreater(len(manifest["codeowners"]), 0)

    def test_hacs_schema(self) -> None:
        """Verify hacs.json conforms to HACS Action validation requirements."""
        self.assertTrue(os.path.exists(self.hacs_path), "hacs.json missing")
        with open(self.hacs_path, "r", encoding="utf-8") as fp:
            hacs = json.load(fp)

        self.assertIn("name", hacs)
        self.assertIn("render_readme", hacs)
        self.assertIn("homeassistant", hacs)
        self.assertTrue(hacs["render_readme"])

        # Validate Home Assistant version format (e.g. 2024.4.0)
        version_pattern = r"^\d{4}\.\d{1,2}\.\d{1,2}$"
        self.assertTrue(
            re.match(version_pattern, hacs["homeassistant"]),
            f"Invalid HA version in hacs.json: {hacs['homeassistant']}",
        )

    def test_translations_parity(self) -> None:
        """Verify complete parity between strings.json, en.json, and es.json."""
        with open(self.strings_path, "r", encoding="utf-8") as fp:
            strings = json.load(fp)
        with open(self.en_path, "r", encoding="utf-8") as fp:
            en = json.load(fp)
        with open(self.es_path, "r", encoding="utf-8") as fp:
            es = json.load(fp)

        # Check top-level sections
        self.assertEqual(set(strings.keys()), set(en.keys()))
        self.assertEqual(set(strings.keys()), set(es.keys()))

        # Check config steps parity
        strings_steps = set(strings.get("config", {}).get("step", {}).keys())
        en_steps = set(en.get("config", {}).get("step", {}).keys())
        es_steps = set(es.get("config", {}).get("step", {}).keys())
        self.assertEqual(strings_steps, en_steps)
        self.assertEqual(strings_steps, es_steps)
        self.assertIn("user", strings_steps)
        self.assertIn("models", strings_steps)

        # Check entity platform parity
        strings_entities = set(strings.get("entity", {}).keys())
        en_entities = set(en.get("entity", {}).keys())
        es_entities = set(es.get("entity", {}).keys())
        self.assertEqual(strings_entities, en_entities)
        self.assertEqual(strings_entities, es_entities)

        # Check for empty strings in all translation files
        def check_no_empty_strings(obj: dict | list | str, path: str = "") -> None:
            if isinstance(obj, dict):
                for k, v in obj.items():
                    check_no_empty_strings(v, f"{path}.{k}")
            elif isinstance(obj, list):
                for i, v in enumerate(obj):
                    check_no_empty_strings(v, f"{path}[{i}]")
            elif isinstance(obj, str):
                self.assertGreater(
                    len(obj.strip()),
                    0,
                    f"Empty translation string found at: {path}",
                )

        check_no_empty_strings(strings, "strings.json")
        check_no_empty_strings(en, "en.json")
        check_no_empty_strings(es, "es.json")

    def test_services_yaml(self) -> None:
        """Verify services.yaml exposes services registered in __init__.py."""
        self.assertTrue(os.path.exists(self.services_path), "services.yaml missing")
        with open(self.services_path, "r", encoding="utf-8") as fp:
            content = fp.read()

        # Check that registered service constants are documented in services.yaml
        self.assertIn(f"{SERVICE_SET_WEEKLY_TIMER}:", content)
        self.assertIn(f"{SERVICE_FORCE_DHW_BOOST}:", content)
        self.assertIn(f"{SERVICE_SET_HOLIDAY_MODE}:", content)
        self.assertIn(f"{SERVICE_CANCEL_HOLIDAY_MODE}:", content)

        # Check basic schema presence: name, description, fields
        self.assertIn("name:", content)
        self.assertIn("description:", content)
        self.assertIn("fields:", content)

    def test_brand_assets(self) -> None:
        """Verify Home Assistant local brand icons exist as valid RGBA PNGs with exact dimensions."""
        brand_dir = os.path.join(self.component_dir, "brand")
        expected = {
            "icon.png": (256, 256),
            "icon@2x.png": (512, 512),
            "logo.png": (256, 256),
            "logo@2x.png": (512, 512),
        }
        for filename, (exp_w, exp_h) in expected.items():
            path = os.path.join(brand_dir, filename)
            self.assertTrue(os.path.exists(path), f"Missing brand asset: {filename}")
            with open(path, "rb") as fp:
                header = fp.read(26)
            # PNG signature (8 bytes) + IHDR length (4) + 'IHDR' (4) + width (4) + height (4) + bit_depth (1) + color_type (1)
            self.assertEqual(
                header[:8], b"\x89PNG\r\n\x1a\n", f"{filename} is not a valid PNG"
            )
            self.assertEqual(header[12:16], b"IHDR")
            width, height, bit_depth, color_type = struct.unpack(">IIBB", header[16:26])
            self.assertEqual(
                (width, height), (exp_w, exp_h), f"Invalid dimensions for {filename}"
            )
            self.assertEqual(bit_depth, 8)
            self.assertEqual(
                color_type,
                6,
                f"{filename} must be RGBA (color_type=6) for transparency",
            )

    def test_icons_schema(self) -> None:
        """Verify icons.json exists, complies with HACS/Hassfest and maps to valid MDI icons."""
        self.assertTrue(
            os.path.exists(self.icons_path), "icons.json missing in integration root"
        )
        with open(self.icons_path, "r", encoding="utf-8") as fp:
            icons = json.load(fp)

        # MDI validation pattern: must start with 'mdi:' followed by lowercase alphanumeric/hyphen
        mdi_pattern = re.compile(r"^mdi:[a-z0-9-]+$")

        def validate_icons(obj: Any, path: str = "") -> None:
            if isinstance(obj, str):
                self.assertTrue(
                    obj.startswith("mdi:"),
                    f"Icon at {path} ('{obj}') must start with 'mdi:'",
                )
                self.assertTrue(
                    mdi_pattern.match(obj),
                    f"Icon at {path} ('{obj}') contains invalid characters",
                )
            elif isinstance(obj, dict):
                for k, v in obj.items():
                    validate_icons(v, f"{path}.{k}" if path else k)
            elif isinstance(obj, list):
                for idx, v in enumerate(obj):
                    validate_icons(v, f"{path}[{idx}]")

        validate_icons(icons)

        # Verify services mapped in icons.json exist in services.yaml
        with open(self.services_path, "r", encoding="utf-8") as fp:
            services_content = fp.read()

        for service_name in icons.get("services", {}):
            self.assertIn(
                f"{service_name}:",
                services_content,
                f"Service '{service_name}' in icons.json does not exist in services.yaml",
            )

        # Verify entities mapped in icons.json exist in strings.json
        with open(self.strings_path, "r", encoding="utf-8") as fp:
            strings_data = json.load(fp)

        strings_entities = strings_data.get("entity", {})
        for platform, entities in icons.get("entity", {}).items():
            self.assertIn(
                platform,
                strings_entities,
                f"Platform '{platform}' in icons.json not found in strings.json",
            )
            for entity_key in entities:
                self.assertIn(
                    entity_key,
                    strings_entities[platform],
                    f"Entity '{platform}.{entity_key}' in icons.json not found in strings.json",
                )

        # Confirm critical dynamic state icon mappings
        self.assertIn("dhw_water_heater", icons["entity"]["water_heater"])
        self.assertIn("hmu_status_code", icons["entity"]["sensor"])
        self.assertIn("zone_1_climate", icons["entity"]["climate"])
        self.assertIn("z1_op_mode", icons["entity"]["select"])
        self.assertIn("dhw_boost_switch", icons["entity"]["switch"])


if __name__ == "__main__":
    unittest.main()
