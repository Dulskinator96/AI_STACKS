"""Pure contract checks; not substitutes for actual inference."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    "real_mempalace_collab", Path(__file__).with_name("knowledge_collaboration.py"))
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class CollaborationContracts(unittest.TestCase):
    def test_exact_code_required(self):
        self.assertTrue(MODULE.exact("TARGETAABBCC", "TARGETAABBCC"))
        self.assertFalse(MODULE.exact("my guess TARGETAABBCC", "TARGETAABBCC"))

    def test_different_models_required(self):
        with self.assertRaisesRegex(ValueError, "differ"):
            MODULE.run("same", "same")

    def test_unavailable_model_is_failure_not_synthetic_success(self):
        with patch.object(MODULE.urllib.request, "urlopen",
                          side_effect=OSError("no Ollama server")):
            with self.assertRaises(OSError):
                MODULE.infer("real", "question")


if __name__ == "__main__":
    unittest.main()
