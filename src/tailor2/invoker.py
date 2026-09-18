"""Model invoker and safety boundary for Tailor2.

Enforces:
- Explicit provider and model required for all live runs (no silent defaulting).
- Pure text-in/text-out with zero tools, filesystem authority, or session persistence.
- Zero credential logging or exposure.
- I11 trace logging for every invocation via src.llm_trace.write_trace.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from src.llm_trace import write_trace
from src.tailor.invoke import invoke_text_model
from src.tailor.providers import Provider, build_model_command


class Tailor2Invoker:
    def __init__(
        self,
        provider: str | Provider,
        model: str | None,
        timeout_seconds: int = 300,
        dry_run: bool = False,
        fake_responses: dict[str, str] | None = None,
        trace_dir: Path = Path("data/traces"),
    ) -> None:
        if isinstance(provider, str):
            try:
                self.provider = Provider(provider.lower())
            except ValueError:
                raise ValueError(
                    f"unknown provider {provider!r}; expected one of {[p.value for p in Provider]}"
                )
        else:
            self.provider = provider

        self.dry_run = dry_run
        self.fake_responses = fake_responses
        self.timeout_seconds = timeout_seconds
        self.trace_dir = Path(trace_dir)

        # Rule: Explicit model name is REQUIRED for live runs.
        if not dry_run and fake_responses is None:
            if not model or not str(model).strip():
                raise ValueError(
                    "Explicit --model name is required for live runs. Do not silently default."
                )
            self.model = str(model).strip()
        else:
            self.model = str(model).strip() if model else "fake-model"

        if not dry_run and fake_responses is None:
            self.cmd = build_model_command(self.provider, self.model)
        else:
            self.cmd = None

    def invoke(
        self,
        prompt: str,
        invocation_type: str,
        input_paths: list[Path] | None = None,
    ) -> str:
        """Invoke model with prompt and record I11 trace."""
        if self.fake_responses is not None:
            raw_output = self.fake_responses.get(invocation_type, "")
        elif self.dry_run:
            raw_output = f"[DRY-RUN] {invocation_type} output placeholder"
        else:
            assert self.cmd is not None
            res = invoke_text_model(prompt, command=self.cmd, timeout=self.timeout_seconds)
            raw_output = res.raw_stdout

        # Record I11 trace
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as tf:
            tf.write(prompt)
            prompt_file = Path(tf.name)

        try:
            write_trace(
                invocation_type=f"tailor2_{invocation_type}",
                input_paths=input_paths or [],
                raw_output=raw_output,
                prompt_path=prompt_file,
                model=self.model,
                trace_dir=self.trace_dir,
            )
        finally:
            prompt_file.unlink(missing_ok=True)

        return raw_output
