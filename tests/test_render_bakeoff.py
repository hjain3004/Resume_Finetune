import pytest
from pathlib import Path
from src.render.model import RenderDoc
from scripts.render_bakeoff import _try

def test_try_catches_exception_and_prints(capsys, monkeypatch):
    doc = RenderDoc(
        identity={}, education=(), experience=(), projects=(),
        skills={}, section_order=(), ats={}
    )
    def broken():
        raise RuntimeError("simulated tool failure")

    _try("Test Label", broken, doc)
    out, err = capsys.readouterr()
    assert "Test Label: UN-RUNNABLE (simulated tool failure)" in out


def test_try_runs_l7_on_success(capsys, monkeypatch, tmp_path):
    doc = RenderDoc(
        identity={}, education=(), experience=(), projects=(),
        skills={}, section_order=(), ats={}
    )
    
    # Mock parse_pdf and run_l7
    def mock_parse(path):
        assert path == tmp_path / "mock.pdf"
        return "mock_parsed_pdf"
        
    def mock_l7(d, p):
        assert d is doc
        assert p == "mock_parsed_pdf"
        return ["mock violation 1", "mock violation 2"]

    monkeypatch.setattr("scripts.render_bakeoff.parse_pdf", mock_parse)
    monkeypatch.setattr("scripts.render_bakeoff.run_l7", mock_l7)

    def success():
        return tmp_path / "mock.pdf"

    _try("Test Label", success, doc)
    
    out, err = capsys.readouterr()
    assert "Test Label:" in out
    assert "L7 FAIL (2)" in out
    assert "- mock violation 1" in out
    assert "- mock violation 2" in out


def test_try_reports_pass_on_zero_violations(capsys, monkeypatch, tmp_path):
    doc = RenderDoc(
        identity={}, education=(), experience=(), projects=(),
        skills={}, section_order=(), ats={}
    )
    
    monkeypatch.setattr("scripts.render_bakeoff.parse_pdf", lambda x: "mock")
    monkeypatch.setattr("scripts.render_bakeoff.run_l7", lambda d, p: [])

    def success():
        return tmp_path / "mock.pdf"

    _try("Test Label", success, doc)
    
    out, err = capsys.readouterr()
    assert "L7 PASS" in out
