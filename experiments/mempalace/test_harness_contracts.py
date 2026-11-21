"""Offline scorer/guard tests only; does not emulate LLM inference."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


FILE = Path(__file__).with_name("tomb_relocation.py")
SPEC = importlib.util.spec_from_file_location("mem_palace_real", FILE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HarnessContracts(unittest.TestCase):
    def test_exact_marker_found(self):
        self.assertTrue(MODULE.contains("Model B said ABCDEF.", "ABCDEF"))

    def test_missing_marker_is_not_success(self):
        self.assertFalse(MODULE.contains("Model B said UNKNOWN.", "ABCDEF"))

    def test_distinct_model_ids_required_before_calls(self):
        with self.assertRaisesRegex(ValueError, "distinct"):
            MODULE.experiment("same", "same")

    def test_model_call_requires_actual_network(self):
        with patch.object(MODULE.urllib.request, "urlopen", side_effect=OSError("offline")):
            with self.assertRaises(OSError):
                MODULE.call_model("real-model", "question")


if __name__ == "__main__":
    unittest.main()
