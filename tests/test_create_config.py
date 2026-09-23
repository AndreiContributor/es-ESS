"""Hardware-free tests for the interactive configuration wizard."""

import configparser
from datetime import datetime
import importlib.util
from io import StringIO
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "create-config.py"
SPEC = importlib.util.spec_from_file_location("create_config", SCRIPT)
create_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(create_config)


class PromptAnswers:
    def __init__(self, answers=None, secrets=None):
        self.answers = answers or {}
        self.secrets = secrets or {}
        self.prompts = []
        self.secret_prompts = []

    def input(self, prompt):
        self.prompts.append(prompt)
        for prefix, answer in self.answers.items():
            if prompt.startswith(prefix):
                return answer
        return ""

    def secret(self, prompt):
        self.secret_prompts.append(prompt)
        for prefix, answer in self.secrets.items():
            if prompt.startswith(prefix):
                return answer
        return ""


def load_generated(text):
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read_string(text)
    return config


class ConfigWizardTests(unittest.TestCase):
    def sample(self):
        return create_config.load_sample(ROOT / "config.sample.ini")

    def test_minimal_wizard_keeps_all_active_services_disabled(self):
        answers = PromptAnswers(answers={"VRM portal ID": "synthetic-portal-id"})
        output = StringIO()
        wizard = create_config.ConfigWizard(
            self.sample(), answers.input, answers.secret, output
        )

        config = wizard.build()

        self.assertEqual(config["Common"]["VRMPortalID"], "synthetic-portal-id")
        self.assertEqual(config["Common"]["ConfigVersion"], "17")
        self.assertEqual(
            set(config._sections["Services"]), set(create_config.ACTIVE_SERVICES)
        )
        for service in create_config.ACTIVE_SERVICES:
            self.assertEqual(config["Services"][service], "false")

    def test_wattpilot_enables_distributor_and_escapes_literal_percent_password(self):
        answers = PromptAnswers(
            answers={
                "VRM portal ID": "synthetic-portal-id",
                "Enable FroniusWattpilot": "yes",
                "Wattpilot host": "charger.example.test",
            },
            secrets={"Wattpilot device/app-access password": "safe%pass"},
        )
        output = StringIO()
        wizard = create_config.ConfigWizard(
            self.sample(), answers.input, answers.secret, output
        )

        config = wizard.build()
        text = create_config.serialized_config(config)
        loaded = load_generated(text)

        self.assertEqual(config["Services"]["FroniusWattpilot"], "true")
        self.assertEqual(config["Services"]["SolarOverheadDistributor"], "true")
        self.assertEqual(
            config["FroniusWattpilot"]["VehiclePhaseCapability"], "Automatic"
        )
        self.assertEqual(loaded["FroniusWattpilot"]["Password"], "safe%pass")
        self.assertIn("Password=safe%%pass", text)
        self.assertNotIn("safe%pass", output.getvalue())

    def test_wattpilot_sample_keys_are_all_preserved_by_wizard(self):
        answers = PromptAnswers(
            answers={
                "VRM portal ID": "synthetic-portal-id",
                "Enable FroniusWattpilot": "yes",
                "Wattpilot host": "charger.example.test",
            },
            secrets={"Wattpilot device/app-access password": "synthetic-secret"},
        )
        wizard = create_config.ConfigWizard(
            self.sample(), answers.input, answers.secret, StringIO()
        )
        configured_keys = set()
        original_set_value = wizard.set_value

        def recording_set_value(section, key, value):
            configured_keys.add((section, key))
            original_set_value(section, key, value)

        wizard.set_value = recording_set_value
        config = wizard.build()
        sample = self.sample()

        self.assertEqual(
            set(config._sections["FroniusWattpilot"]),
            set(sample._sections["FroniusWattpilot"]),
        )
        self.assertEqual(
            {key for section, key in configured_keys if section == "FroniusWattpilot"},
            set(sample._sections["FroniusWattpilot"]),
        )

    def test_no_bat_to_ev_is_disabled_for_battery_assist_no_grid_profile(self):
        answers = PromptAnswers(
            answers={
                "VRM portal ID": "synthetic-portal-id",
                "Enable FroniusWattpilot": "yes",
                "Enable NoBatToEV": "yes",
                "Wattpilot host": "charger.example.test",
            },
            secrets={"Wattpilot device/app-access password": "synthetic-secret"},
        )
        wizard = create_config.ConfigWizard(
            self.sample(), answers.input, answers.secret, StringIO()
        )

        config = wizard.build()

        self.assertEqual(config["FroniusWattpilot"]["BatteryAssistEnabled"], "true")
        self.assertEqual(config["FroniusWattpilot"]["AllowGridCharging"], "false")
        self.assertEqual(config["Services"]["NoBatToEV"], "false")

    def test_temperature_service_creates_repeatable_instance_section(self):
        answers = PromptAnswers(
            answers={
                "VRM portal ID": "synthetic-portal-id",
                "Enable MqttTemperature": "yes",
                "Number of MQTT temperature sensors": "1",
                "MqttTemperature #1 unique key": "outside",
                "VRM instance ID": "1100",
                "Display name": "Outside",
                "Temperature MQTT topic": "site/weather/temperature",
                "Humidity MQTT topic": "site/weather/humidity",
            }
        )
        wizard = create_config.ConfigWizard(
            self.sample(), answers.input, answers.secret, StringIO()
        )

        config = wizard.build()

        section = config["MqttTemperature:outside"]
        self.assertEqual(section["VRMInstanceID"], "1100")
        self.assertEqual(section["Topic"], "site/weather/temperature")
        self.assertEqual(section["TopicHumidity"], "site/weather/humidity")
        self.assertEqual(section["TopicPressure"], "")

    def test_numeric_prompt_repeats_until_value_is_in_range(self):
        responses = iter(("5", "33", "16"))
        output = StringIO()
        wizard = create_config.ConfigWizard(
            self.sample(), lambda _prompt: next(responses), lambda _prompt: "", output
        )

        value = wizard.ask_int("Current", minimum=6, maximum=32)

        self.assertEqual(value, 16)
        self.assertIn("must be at least 6", output.getvalue())
        self.assertIn("must be at most 32", output.getvalue())

    def test_url_validation_requires_complete_http_url(self):
        for value in ("r", "http://", "http\\://device.example.test/status"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    create_config._validate_url(value)

        self.assertEqual(
            create_config._validate_url("http://device.example.test/status"),
            "http://device.example.test/status",
        )

    def test_invalid_optional_url_reprompts_and_allows_empty_value(self):
        responses = iter(("r", ""))
        output = StringIO()
        wizard = create_config.ConfigWizard(
            self.sample(), lambda _prompt: next(responses), lambda _prompt: "", output
        )

        value = wizard.ask(
            "Power URL (optional)",
            allow_empty=True,
            validator=create_config._validate_url,
        )

        self.assertEqual(value, "")
        self.assertIn("complete http:// or https:// URL", output.getvalue())

    def test_write_is_atomic_and_backs_up_existing_config(self):
        config = self.sample()
        config["Common"]["VRMPortalID"] = "new-synthetic-id"
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.ini"
            target.write_text("old private configuration\n", encoding="utf-8")

            backup = create_config.write_config(
                config,
                target,
                replace=True,
                now=datetime(2000, 1, 2, 3, 4, 5),
            )

            self.assertEqual(backup.name, "config.ini.20000102-030405.backup")
            self.assertEqual(
                backup.read_text(encoding="utf-8"), "old private configuration\n"
            )
            generated = load_generated(target.read_text(encoding="utf-8"))
            self.assertEqual(generated["Common"]["VRMPortalID"], "new-synthetic-id")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_existing_config_requires_explicit_replace(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "config.ini"
            target.write_text("existing\n", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                create_config.write_config(self.sample(), target)

            self.assertEqual(target.read_text(encoding="utf-8"), "existing\n")

    def test_runtime_escaped_sample_percent_is_not_double_escaped(self):
        with tempfile.TemporaryDirectory() as directory:
            sample_path = Path(directory) / "sample.ini"
            sample_path.write_text(
                "[Credentials]\nPassword=one%%two\n", encoding="utf-8"
            )

            config = create_config.load_sample(sample_path)
            text = create_config.serialized_config(config)

            self.assertEqual(config["Credentials"]["Password"], "one%two")
            self.assertIn("Password=one%%two", text)
            self.assertNotIn("Password=one%%%%two", text)

    def test_dormant_services_are_never_offered(self):
        self.assertTrue(
            create_config.DORMANT_SERVICES.isdisjoint(create_config.ACTIVE_SERVICES)
        )

    def test_wizard_service_choices_match_maintained_sample(self):
        sample = self.sample()

        self.assertEqual(
            set(create_config.ACTIVE_SERVICES),
            set(sample._sections["Services"]),
        )


if __name__ == "__main__":
    unittest.main()
