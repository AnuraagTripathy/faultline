"""Production environment validation tests."""

from __future__ import annotations

import os
import unittest

from cloud.api.env_validation import validate_startup_config


class TestEnvValidation(unittest.TestCase):
    def tearDown(self) -> None:
        for key in (
            "FAULTLINE_ENV",
            "FAULTLINE_JWT_SECRET",
            "FAULTLINE_SEED_DEMO",
            "FAULTLINE_COOKIE_SECURE",
        ):
            os.environ.pop(key, None)

    def test_production_rejects_short_jwt(self) -> None:
        os.environ["FAULTLINE_ENV"] = "production"
        os.environ["FAULTLINE_JWT_SECRET"] = "short"
        os.environ["FAULTLINE_COOKIE_SECURE"] = "true"
        with self.assertRaises(RuntimeError):
            validate_startup_config()

    def test_production_rejects_demo_seed(self) -> None:
        os.environ["FAULTLINE_ENV"] = "production"
        os.environ["FAULTLINE_JWT_SECRET"] = "x" * 32
        os.environ["FAULTLINE_SEED_DEMO"] = "1"
        os.environ["FAULTLINE_COOKIE_SECURE"] = "true"
        with self.assertRaises(RuntimeError):
            validate_startup_config()

    def test_development_allows_dev_defaults(self) -> None:
        os.environ["FAULTLINE_ENV"] = "development"
        os.environ["FAULTLINE_JWT_SECRET"] = "dev"
        os.environ["FAULTLINE_SEED_DEMO"] = "1"
        validate_startup_config()


if __name__ == "__main__":
    unittest.main()
