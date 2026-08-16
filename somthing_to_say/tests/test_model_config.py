import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ModelConfigContractTests(unittest.TestCase):
    def test_uses_deepseek_models(self):
        source = (ROOT / "config.py").read_text(encoding="utf-8")
        self.assertIn('PRIMARY_MODEL = "deepseek:deepseek-v4-flash"', source)
        self.assertIn('FALLBACK_MODEL = "deepseek:deepseek-v4-pro"', source)

    def test_agent_factory_uses_deepseek_provider(self):
        source = (ROOT / "agent_factory.py").read_text(encoding="utf-8")
        self.assertIn("from langchain.chat_models import init_chat_model", source)
        self.assertIn("primary = init_chat_model(PRIMARY_MODEL, temperature=0)", source)
        self.assertIn(
            "fallback = init_chat_model(FALLBACK_MODEL, temperature=0, max_tokens=200)",
            source,
        )
        self.assertNotIn("OPENROUTER_API_KEY", source)


if __name__ == "__main__":
    unittest.main()
