"""Unit tests for schema integrity, manifest, translations, and services validation."""

import csv
import glob
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
    SERVICE_CANCEL_QUICK_VETO,
    SERVICE_DUMP_MQTT_VALUES,
    SERVICE_FORCE_DHW_BOOST,
    SERVICE_QUICK_VETO,
    SERVICE_READ_PARAMETER,
    SERVICE_RECORD_TOPIC_CHANGES,
    SERVICE_SEND_HEX_COMMAND,
    SERVICE_SET_HOLIDAY_MODE,
    SERVICE_SET_LEGIONELLA_PROTECTION,
    SERVICE_SET_WEEKLY_TIMER,
    SERVICE_WRITE_PARAMETER,
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
        self.de_path = os.path.join(self.component_dir, "translations", "de.json")
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
            "categories",
            "codeowners",
            "config_flow",
            "documentation",
            "iot_class",
            "issue_tracker",
            "version",
        ]
        for key in required_keys:
            self.assertIn(key, manifest, f"Missing key in manifest.json: {key}")

        # Hassfest key ordering: domain, name, then alphabetical
        keys = list(manifest.keys())
        self.assertEqual(keys[:2], ["domain", "name"])
        self.assertEqual(keys[2:], sorted(keys[2:]))

        self.assertEqual(manifest["domain"], DOMAIN)
        self.assertEqual(manifest["domain"], "arotherm_genia_ebusd")
        self.assertTrue(manifest["config_flow"])
        self.assertIn(
            manifest["iot_class"],
            ["local_push", "local_polling", "cloud_push", "cloud_polling"],
        )
        self.assertTrue(isinstance(manifest["categories"], list))
        self.assertTrue(1 <= len(manifest["categories"]) <= 3)
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
        """Verify complete parity between strings.json, en.json, es.json, and de.json."""
        with open(self.strings_path, "r", encoding="utf-8") as fp:
            strings = json.load(fp)
        with open(self.en_path, "r", encoding="utf-8") as fp:
            en = json.load(fp)
        with open(self.es_path, "r", encoding="utf-8") as fp:
            es = json.load(fp)
        with open(self.de_path, "r", encoding="utf-8") as fp:
            de = json.load(fp)

        # Check top-level sections
        self.assertEqual(set(strings.keys()), set(en.keys()))
        self.assertEqual(set(strings.keys()), set(es.keys()))
        self.assertEqual(set(strings.keys()), set(de.keys()))

        # Check config steps parity
        strings_steps = set(strings.get("config", {}).get("step", {}).keys())
        en_steps = set(en.get("config", {}).get("step", {}).keys())
        es_steps = set(es.get("config", {}).get("step", {}).keys())
        de_steps = set(de.get("config", {}).get("step", {}).keys())
        self.assertEqual(strings_steps, en_steps)
        self.assertEqual(strings_steps, es_steps)
        self.assertEqual(strings_steps, de_steps)
        self.assertIn("user", strings_steps)
        self.assertIn("models", strings_steps)

        # Check entity platform parity
        strings_entities = set(strings.get("entity", {}).keys())
        en_entities = set(en.get("entity", {}).keys())
        es_entities = set(es.get("entity", {}).keys())
        de_entities = set(de.get("entity", {}).keys())
        self.assertEqual(strings_entities, en_entities)
        self.assertEqual(strings_entities, es_entities)
        self.assertEqual(strings_entities, de_entities)

        # Check services parity
        strings_services = set(strings.get("services", {}).keys())
        en_services = set(en.get("services", {}).keys())
        es_services = set(es.get("services", {}).keys())
        de_services = set(de.get("services", {}).keys())
        self.assertEqual(strings_services, en_services)
        self.assertEqual(strings_services, es_services)
        self.assertEqual(strings_services, de_services)
        self.assertIn("set_weekly_timer", strings_services)
        self.assertIn("force_dhw_boost", strings_services)

        # Every service declared in services.yaml must also have translations
        with open(self.services_path, "r", encoding="utf-8") as fp:
            yaml_services = {
                line.rstrip(":")
                for line in fp.read().splitlines()
                if line and not line[0].isspace() and line.endswith(":")
            }
        self.assertEqual(yaml_services, strings_services)

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
        check_no_empty_strings(de, "de.json")

    def test_services_yaml(self) -> None:
        """Verify services.yaml exposes services registered in __init__.py."""
        self.assertTrue(os.path.exists(self.services_path), "services.yaml missing")
        with open(self.services_path, "r", encoding="utf-8") as fp:
            content = fp.read()

        # Check that registered service constants are documented in services.yaml
        self.assertIn(f"{SERVICE_SET_WEEKLY_TIMER}:", content)
        self.assertIn(f"{SERVICE_FORCE_DHW_BOOST}:", content)
        self.assertIn(f"{SERVICE_SET_LEGIONELLA_PROTECTION}:", content)
        self.assertIn(f"{SERVICE_SET_HOLIDAY_MODE}:", content)
        self.assertIn(f"{SERVICE_CANCEL_HOLIDAY_MODE}:", content)
        self.assertIn(f"{SERVICE_QUICK_VETO}:", content)
        self.assertIn(f"{SERVICE_CANCEL_QUICK_VETO}:", content)
        self.assertIn(f"{SERVICE_DUMP_MQTT_VALUES}:", content)
        self.assertIn(f"{SERVICE_RECORD_TOPIC_CHANGES}:", content)
        self.assertIn(f"{SERVICE_SEND_HEX_COMMAND}:", content)
        self.assertIn(f"{SERVICE_READ_PARAMETER}:", content)
        self.assertIn(f"{SERVICE_WRITE_PARAMETER}:", content)

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

    def test_ebusd_csv_field_types(self) -> None:
        """Verify that all eBUSd CSV definitions contain strictly valid eBUSd data types."""
        ebusd_cfg_dir = os.path.join(self.root_dir, "ebusd-configuration")
        csv_files = glob.glob(
            os.path.join(ebusd_cfg_dir, "**", "*.csv"), recursive=True
        )
        self.assertGreater(len(csv_files), 0, "No CSV configuration files found")

        # Official ebusd field type prefixes (Wiki 4.1 Data-types)
        valid_prefixes = (
            "HEX",
            "IGN",
            "UCH",
            "SCH",
            "UIN",
            "SIN",
            "ULG",
            "SLG",
            "FLT",
            "EXP",
            "D1C",
            "D1B",
            "D2C",
            "D2B",
            "HTM",
            "BDA",
            "BTI",
            "VTI",
            "VTM",
            "DAY",
            "BI",
            "STR",
            "TTH",
            "PIN",
            "HDA",
            "HTI",
        )

        for csv_path in csv_files:
            rel_path = os.path.relpath(csv_path, self.root_dir)
            with open(csv_path, "r", encoding="utf-8", errors="replace") as fp:
                for line_no, raw_line in enumerate(fp, start=1):
                    line = raw_line.strip()
                    if not line or line.startswith(("#", "*")):
                        continue
                    parts = next(iter(csv.reader([line])))
                    # In ebusd CSV files, fields are formatted in groups of 6:
                    # name (idx 9), part (idx 10), type (idx 11), divisor (idx 12), unit (idx 13), comment (idx 14)
                    for idx in range(9, len(parts), 6):
                        if idx + 2 < len(parts):
                            fname = parts[idx].strip()
                            ftype = parts[idx + 2].strip()
                            if ftype and fname != "*name":
                                base_type = ftype.split(":")[0].upper()
                                self.assertTrue(
                                    any(
                                        base_type.startswith(vp)
                                        for vp in valid_prefixes
                                    ),
                                    f"Invalid ebusd field type '{ftype}' for field '{fname}' in {rel_path}:{line_no}",
                                )

    def test_ebusd_csv_first_line_header(self) -> None:
        """Verify that all eBUSd CSV files start immediately with the header definition on line 1.

        ebusd daemon requires line 1 to be the column header; comments before line 1
        prevent the parser from properly detecting the column format and loading messages.
        """
        ebusd_cfg_dir = os.path.join(self.root_dir, "ebusd-configuration")
        csv_files = glob.glob(
            os.path.join(ebusd_cfg_dir, "**", "*.csv"), recursive=True
        )
        self.assertGreater(len(csv_files), 0, "No CSV configuration files found")
        expected_header = "type,circuit,level,name,comment,qq,zz,pbsb,id,*name,part,type,divisor/values,unit,comment"

        for csv_path in csv_files:
            rel_path = os.path.relpath(csv_path, self.root_dir)
            with open(csv_path, "r", encoding="utf-8") as fp:
                first_line = fp.readline().strip()
            self.assertEqual(
                first_line,
                expected_header,
                f"CSV file '{rel_path}' must begin with the header definition on line 1, found: {first_line!r}",
            )

    def test_ebusd_csv_no_duplicate_ids(self) -> None:
        """Verify that no eBUSd CSV definition contains duplicate (type, pbsb, id) entries.

        Duplicate IDs cause the ebusd parser to abort reading the CSV file with
        'ERR: duplicate entry, duplicate ID', leaving subsequent registers unloaded.
        """
        ebusd_cfg_dir = os.path.join(self.root_dir, "ebusd-configuration")
        csv_files = glob.glob(
            os.path.join(ebusd_cfg_dir, "**", "*.csv"), recursive=True
        )
        self.assertGreater(len(csv_files), 0, "No CSV configuration files found")

        for csv_path in csv_files:
            rel_path = os.path.relpath(csv_path, self.root_dir)
            seen_entries: dict[tuple[str, str, str, str, str], int] = {}
            with open(csv_path, "r", encoding="utf-8", errors="replace") as fp:
                for line_no, raw_line in enumerate(fp, start=1):
                    line = raw_line.strip()
                    if not line or line.startswith(("#", "*")):
                        continue
                    parts = next(csv.reader([line]))
                    if len(parts) >= 9:
                        cmd_type = parts[0].strip()
                        circuit = parts[1].strip()
                        level = parts[2].strip()
                        pbsb = parts[7].strip()
                        msg_id = parts[8].strip()
                        key = (cmd_type, circuit, level, pbsb, msg_id)
                        self.assertNotIn(
                            key,
                            seen_entries,
                            f"Duplicate ID in {rel_path}:{line_no} matching line {seen_entries.get(key)}: {key}",
                        )
                        seen_entries[key] = line_no

    def test_hmu_csvs_stay_identical(self) -> None:
        """Verify that 08.hmu.csv and 08.hmu.HW5103.csv stay byte-for-byte identical.

        ebusd prioritizes 08.hmu.HW5103.csv when matching HW=5103. Both files
        must stay byte-for-byte identical so that updating either file ensures parity.
        """
        ebusd_cfg_dir = os.path.join(self.root_dir, "ebusd-configuration", "vaillant")
        hmu_path = os.path.join(ebusd_cfg_dir, "08.hmu.csv")
        hmu_hw_path = os.path.join(ebusd_cfg_dir, "08.hmu.HW5103.csv")
        self.assertTrue(os.path.exists(hmu_path), "08.hmu.csv missing")
        self.assertTrue(os.path.exists(hmu_hw_path), "08.hmu.HW5103.csv missing")
        with open(hmu_path, "rb") as fp:
            hmu_bytes = fp.read()
        with open(hmu_hw_path, "rb") as fp:
            hmu_hw_bytes = fp.read()
        self.assertEqual(
            hmu_bytes,
            hmu_hw_bytes,
            "08.hmu.HW5103.csv must be byte-for-byte identical to 08.hmu.csv",
        )

    def test_controller_csvs_stay_identical_and_valid_types(self) -> None:
        """Verify 15.*.csv parity, Unix LF line endings, and valid eBUSd message types."""
        ebusd_cfg_dir = os.path.join(self.root_dir, "ebusd-configuration")
        vaillant_dir = os.path.join(ebusd_cfg_dir, "vaillant")

        # 1. Verify all 4 controller CSVs stay byte-for-byte identical
        with open(os.path.join(vaillant_dir, "15.bass3.csv"), "rb") as fp:
            bass3_bytes = fp.read()
        for fname in ("15.basv3.csv", "15.ctlv2.csv", "15.ctlv3.csv"):
            with open(os.path.join(vaillant_dir, fname), "rb") as fp:
                other_bytes = fp.read()
            self.assertEqual(
                bass3_bytes,
                other_bytes,
                f"{fname} must be byte-for-byte identical to 15.bass3.csv",
            )

        # 2. Verify Unix LF line endings and valid message type tokens across all CSVs
        valid_type_tokens = {f"r{i}" for i in range(1, 10)} | {"r", "w", "u", "uw"}
        csv_files = glob.glob(
            os.path.join(ebusd_cfg_dir, "**", "*.csv"), recursive=True
        )
        for csv_path in csv_files:
            rel_path = os.path.relpath(csv_path, self.root_dir)
            with open(csv_path, "rb") as bfp:
                raw_bytes = bfp.read()
            self.assertNotIn(
                b"\r\n",
                raw_bytes,
                f"CSV file '{rel_path}' contains CRLF line endings; use LF for Linux ebusd compatibility",
            )
            for line_no, raw_line in enumerate(
                raw_bytes.decode("utf-8").splitlines(), start=1
            ):
                line = raw_line.strip()
                if not line or line.startswith(("#", "*", "type,")):
                    continue
                parts = next(csv.reader([line]))
                raw_type = re.sub(r"^\[[^\]]+\]", "", parts[0].strip())
                tokens = [t.strip() for t in raw_type.split(";") if t.strip()]
                self.assertGreater(
                    len(tokens), 0, f"Empty type in {rel_path}:{line_no}"
                )
                for tok in tokens:
                    self.assertIn(
                        tok,
                        valid_type_tokens,
                        f"Unexpected ebusd message type token '{tok}' in {rel_path}:{line_no}",
                    )

    def test_legacy_device_name_migration(self) -> None:
        """Verify _async_migrate_legacy_device_names updates legacy Spanish device registry names to English."""
        from unittest.mock import MagicMock, patch

        from homeassistant.helpers import device_registry as dr

        from custom_components.arotherm_genia_ebusd import (
            _async_migrate_legacy_device_names,
        )

        hass = MagicMock()
        entry = MagicMock()
        entry.entry_id = "test_entry_456"

        mock_dev_reg = MagicMock()

        # Legacy Spanish devices
        dev_outdoor = MagicMock()
        dev_outdoor.id = "dev_1"
        dev_outdoor.name = "GeniaAir Max ES 15 (Unidad Exterior)"
        dev_outdoor.name_by_user = None

        dev_controller = MagicMock()
        dev_controller.id = "dev_2"
        dev_controller.name = "MiPro Sense (Regulador Climático)"
        dev_controller.name_by_user = None

        dev_hydraulic = MagicMock()
        dev_hydraulic.id = "dev_3"
        dev_hydraulic.name = "HPIM 7 230V (Interfaz Hidráulica)"
        dev_hydraulic.name_by_user = None

        dev_thermostat = MagicMock()
        dev_thermostat.id = "dev_4"
        dev_thermostat.name = "MiPro Sense (Termostato Inalámbrico)"
        dev_thermostat.name_by_user = None

        # User-customized device (should NOT be overwritten)
        dev_custom = MagicMock()
        dev_custom.id = "dev_5"
        dev_custom.name = "Custom Heat Pump (Unidad Exterior)"
        dev_custom.name_by_user = "My Custom Name"

        # Modern English device (should NOT be changed)
        dev_en = MagicMock()
        dev_en.id = "dev_6"
        dev_en.name = "GeniaAir Max ES 15 (Outdoor Unit)"
        dev_en.name_by_user = None

        devices = [
            dev_outdoor,
            dev_controller,
            dev_hydraulic,
            dev_thermostat,
            dev_custom,
            dev_en,
        ]

        with (
            patch.object(dr, "async_get", return_value=mock_dev_reg),
            patch.object(dr, "async_entries_for_config_entry", return_value=devices),
        ):
            _async_migrate_legacy_device_names(hass, entry)

            mock_dev_reg.async_update_device.assert_any_call(
                "dev_1", name="GeniaAir Max ES 15 (Outdoor Unit)"
            )
            mock_dev_reg.async_update_device.assert_any_call(
                "dev_2", name="MiPro Sense (Climate Controller)"
            )
            mock_dev_reg.async_update_device.assert_any_call(
                "dev_3", name="HPIM 7 230V (Hydraulic Interface)"
            )
            mock_dev_reg.async_update_device.assert_any_call(
                "dev_4", name="MiPro Sense (Wireless Thermostat)"
            )
            self.assertEqual(mock_dev_reg.async_update_device.call_count, 4)


if __name__ == "__main__":
    unittest.main()
