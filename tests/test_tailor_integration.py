"""The single-shot S1/S2/S3/G2 tailor/critic wrapper this file used to
exercise was disabled in M8P-1 (see src/tailor/wrapper.py) -- it dumped the
full master profile into an unrestricted `claude -p` call. This file now
proves that no production path can invoke it. The validated S1 replacement
is covered end to end by tests/tailor/test_s1_pipeline.py and
tests/test_tailor_s1_cli.py."""

import pytest

from src.tailor.wrapper import run_critic, run_tailor, tailor_loop


def test_legacy_tailor_critic_path_is_unavailable():
    with pytest.raises(NotImplementedError):
        run_tailor("test jd", {}, {})
    with pytest.raises(NotImplementedError):
        run_critic("hydrated", "test jd", "banned", "taste")
    with pytest.raises(NotImplementedError):
        tailor_loop("test jd", {}, {}, "banned", "taste")
