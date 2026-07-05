"""Unwrap aggregator/wrapper pages that embed a Greenhouse posting rather than
hosting the JD themselves, per PHASE2_KICKOFF.md M6.0(b)-(c):

- `resolve_gh_jid`: any URL with a `gh_jid` query param (company career-site
  wrappers proxying a Greenhouse posting) — derive the board token by trying,
  in order, the site's second-level domain, then regexing the wrapper page's
  HTML for an embedded `boards.greenhouse.io/{token}` or
  `greenhouse.io/embed/job_board?for={token}` reference.
- `resolve_wrapper_map`: a small hand-maintained map (`config/wrapper_map.yaml`)
  of hostnames known to wrap a specific ATS with a fixed board, for wrappers
  that don't expose a `gh_jid` param at all (e.g. careers.roblox.com).

Both resolve via the existing greenhouse resolver on success and record the
underlying ATS URL in `ResolvedJD.ats_url`.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

from src.models import ResolvedJD
from src.resolve import greenhouse

WRAPPER_MAP_PATH = "config/wrapper_map.yaml"

_BOARD_TOKEN_RE = re.compile(
    r"(?:boards|job-boards)\.greenhouse\.io/(?P<board1>[^/\"'?#]+)/jobs/"
    r"|greenhouse\.io/embed/job_board(?:/js)?\?for=(?P<board2>[^\"'&]+)"
)


def extract_gh_jid(url: str) -> str | None:
    values = parse_qs(urlparse(url).query).get("gh_jid")
    return values[0] if values else None


def second_level_domain(url: str) -> str | None:
    hostname = (urlparse(url).hostname or "").removeprefix("www.")
    labels = hostname.split(".")
    return labels[-2] if len(labels) >= 2 else None


def find_board_token_in_html(html_text: str) -> str | None:
    match = _BOARD_TOKEN_RE.search(html_text or "")
    if not match:
        return None
    return match["board1"] or match["board2"]


def _resolve_via_greenhouse_board(board: str, job_id: str, session) -> ResolvedJD | None:
    greenhouse_url = f"https://boards.greenhouse.io/{board}/jobs/{job_id}"
    result = greenhouse.resolve(greenhouse_url, session)
    if result is None:
        return None
    return ResolvedJD(
        jd_text=result.jd_text,
        resolver=greenhouse.RESOLVER_NAME,
        raw_title=result.raw_title,
        raw_location=result.raw_location,
        ats_url=greenhouse_url,
    )


def resolve_gh_jid(url: str, html_text: str, session) -> ResolvedJD | None:
    job_id = extract_gh_jid(url)
    if job_id is None:
        return None

    candidates: list[str] = []
    domain_guess = second_level_domain(url)
    if domain_guess:
        candidates.append(domain_guess)
    html_guess = find_board_token_in_html(html_text)
    if html_guess and html_guess not in candidates:
        candidates.append(html_guess)

    for board in candidates:
        result = _resolve_via_greenhouse_board(board, job_id, session)
        if result is not None:
            return result
    return None


def load_wrapper_map(path: str | Path = WRAPPER_MAP_PATH) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    return yaml.safe_load(p.read_text()) or {}


def resolve_wrapper_map(
    url: str, session, wrapper_map: dict | None = None
) -> ResolvedJD | None:
    wrapper_map = load_wrapper_map() if wrapper_map is None else wrapper_map
    hostname = urlparse(url).hostname or ""
    entry = wrapper_map.get(hostname)
    if not entry or entry.get("ats") != "greenhouse" or entry.get("id_from") != "path":
        return None
    board = entry.get("board")
    if not board:
        return None

    path_segments = [seg for seg in urlparse(url).path.split("/") if seg]
    if not path_segments or not path_segments[-1].isdigit():
        return None

    return _resolve_via_greenhouse_board(board, path_segments[-1], session)
