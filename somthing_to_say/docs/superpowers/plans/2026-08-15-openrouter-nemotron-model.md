# OpenRouter Nemotron Model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configure the customer service agent to call `nvidia/nemotron-3.5-lightning:free` through OpenRouter.

**Architecture:** Keep model selection in `config.py`. Replace provider inference in `agent_factory.py` with explicit `ChatOpenAI` clients configured with OpenRouter's OpenAI-compatible base URL and an environment-provided API key. Both primary and fallback clients use the configured Nemotron model so the existing middleware pipeline remains unchanged.

**Tech Stack:** Python, LangChain `ChatOpenAI`, OpenRouter OpenAI-compatible API, `unittest`.

---

### Task 1: Add OpenRouter model configuration

**Files:**
- Modify: `config.py`
- Test: `tests/test_model_config.py`

- [ ] **Step 1: Write the failing contract test**

Add tests that read the configuration source and assert the configured model and base URL are present without importing optional runtime dependencies:

```python
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ModelConfigContractTests(unittest.TestCase):
    def test_uses_openrouter_nemotron_model(self):
        source = (ROOT / "config.py").read_text(encoding="utf-8")
        self.assertIn('PRIMARY_MODEL = "nvidia/nemotron-3.5-lightning:free"', source)
        self.assertIn("FALLBACK_MODEL = PRIMARY_MODEL", source)

    def test_defines_openrouter_base_url(self):
        source = (ROOT / "config.py").read_text(encoding="utf-8")
        self.assertIn('OPENROUTER_BASE_URL = os.getenv(', source)
        self.assertIn('"https://openrouter.ai/api/v1"', source)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the contract test and verify it fails**

Run: `python -m unittest tests.test_model_config -v`

Expected: FAIL because `config.py` still names the DeepSeek models and has no OpenRouter base URL.

- [ ] **Step 3: Implement the configuration change**

In `config.py`, keep `import os` and replace the model constants with:

```python
PRIMARY_MODEL = "nvidia/nemotron-3.5-lightning:free"
FALLBACK_MODEL = PRIMARY_MODEL
OPENROUTER_BASE_URL = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
```

- [ ] **Step 4: Run the contract test and verify it passes**

Run: `python -m unittest tests.test_model_config -v`

Expected: PASS.

### Task 2: Construct OpenRouter chat clients explicitly

**Files:**
- Modify: `agent_factory.py`
- Test: `tests/test_model_config.py`

- [ ] **Step 1: Extend the failing contract test**

Add source assertions for the OpenAI-compatible client, explicit OpenRouter key, and missing-key error:

```python
    def test_agent_factory_uses_explicit_openrouter_client(self):
        source = (ROOT / "agent_factory.py").read_text(encoding="utf-8")
        self.assertIn("from langchain_openai import ChatOpenAI", source)
        self.assertIn('os.getenv("OPENROUTER_API_KEY")', source)
        self.assertIn("OPENROUTER_BASE_URL", source)
        self.assertIn("OPENROUTER_API_KEY is required", source)
```

- [ ] **Step 2: Run the contract test and verify it fails**

Run: `python -m unittest tests.test_model_config -v`

Expected: FAIL because `agent_factory.py` still calls `init_chat_model` and never validates the OpenRouter key.

- [ ] **Step 3: Replace provider inference with a small client factory**

In `agent_factory.py`, import `os`, import `ChatOpenAI`, import `OPENROUTER_BASE_URL`, remove `init_chat_model`, and add:

```python
def _build_openrouter_model(model_name: str, *, temperature: int, max_tokens: int) -> ChatOpenAI:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required to use the configured model")
    return ChatOpenAI(
        model=model_name,
        api_key=api_key,
        base_url=OPENROUTER_BASE_URL,
        temperature=temperature,
        max_tokens=max_tokens,
    )
```

Replace the two client construction lines in `build_agent` with:

```python
    primary_max_tokens = 400 if mode == "problem_solving" else 1024
    primary = _build_openrouter_model(
        PRIMARY_MODEL,
        temperature=0,
        max_tokens=primary_max_tokens,
    )
    fallback = _build_openrouter_model(
        FALLBACK_MODEL,
        temperature=0,
        max_tokens=200,
    )
```

- [ ] **Step 4: Run focused checks**

Run: `python -m unittest tests.test_model_config tests.test_problem_solving_backend -v`

Expected: PASS when the project dependencies are installed; otherwise the source-based tests still run without importing the application, and the dependency error is reported separately.

### Task 3: Verify syntax and regression surface

**Files:**
- Verify: `config.py`, `agent_factory.py`, `tests/test_model_config.py`

- [ ] **Step 1: Compile changed Python modules**

Run: `python -m compileall config.py agent_factory.py tests/test_model_config.py`

Expected: exit code 0.

- [ ] **Step 2: Run the full test suite**

Run: `python -m unittest discover -s tests -v`

Expected: all available tests pass; if dependencies are absent, report the exact import failure without exposing environment values.
