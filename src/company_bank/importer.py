import os
import tempfile
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from src.company_bank.model import CompanyDossier
from src.company_bank.policy import to_company_dossier
from src.company_bank.serde import (
    CompanyBankValidationError,
    dump_company_dossier,
    load_seed_companies,
    parse_research_bundle,
)
from src.company_bank.store import load_company_bank


class ImportStatus(str, Enum):
    CREATED = "created"
    UNCHANGED = "unchanged"


@dataclass(frozen=True)
class ImportResult:
    status: ImportStatus
    company_count: int
    target: Path


def validate_corpus(inbox_root: Path, seed_path: Path, *, now: datetime) -> tuple[CompanyDossier, ...]:
    seeds = load_seed_companies(seed_path)
    if not inbox_root.is_dir():
        raise CompanyBankValidationError(f"inbox_root is not a directory: {inbox_root}")

    dossiers = []
    seen_ids = set()
    for company_dir in inbox_root.iterdir():
        if not company_dir.is_dir():
            continue
        
        company_id = company_dir.name
        if company_id not in seeds:
            raise CompanyBankValidationError(f"inbox contains unexpected company directory: {company_id}")
            
        bundle_path = company_dir / "bundle.json"
        if not bundle_path.is_file():
            raise CompanyBankValidationError(f"bundle.json missing in {company_id}")
            
        bundle = parse_research_bundle(bundle_path)
        if bundle.company_id != company_id:
            raise CompanyBankValidationError(f"bundle company_id {bundle.company_id!r} does not match directory {company_id!r}")
            
        if bundle.company_id in seen_ids:
            raise CompanyBankValidationError(f"duplicate company id in inbox: {company_id}")
        seen_ids.add(bundle.company_id)
        
        expected_name = seeds[company_id]
        if bundle.display_name != expected_name:
            raise CompanyBankValidationError(
                f"display_name disagreement for {company_id}: expected {expected_name!r}, got {bundle.display_name!r}"
            )
            
        dossier = to_company_dossier(bundle, company_dir)
        if dossier.researched_at > now:
            raise CompanyBankValidationError(f"bundle researched_at is in the future for {company_id}")
        if dossier.expires_at <= now:
            raise CompanyBankValidationError(f"bundle is expired for {company_id}")
            
        dossiers.append(dossier)

    for sid in seeds:
        if sid not in seen_ids:
            raise CompanyBankValidationError(f"missing bundle for seed company: {sid}")

    dossiers.sort(key=lambda d: d.company_id)
    return tuple(dossiers)


def _files_identical(a: Path, b: Path) -> bool:
    a_entries = {p.name: p for p in a.iterdir()}
    b_entries = {p.name: p for p in b.iterdir()}
    if set(a_entries) != set(b_entries):
        return False
    
    for name, a_path in a_entries.items():
        if not a_path.is_file() or not b_entries[name].is_file():
            return False
        if a_path.read_bytes() != b_entries[name].read_bytes():
            return False
            
    return True


def import_corpus(inbox_root: Path, bank_root: Path, seed_path: Path, *, now: datetime) -> ImportResult:
    dossiers = validate_corpus(inbox_root, seed_path, now=now)
    
    stage = Path(tempfile.mkdtemp(prefix=".companies-stage-", dir=bank_root))
    try:
        for dossier in dossiers:
            yaml_content = dump_company_dossier(dossier)
            (stage / f"{dossier.company_id}.yaml").write_text(yaml_content, encoding="utf-8")
            
        # Parse and validate the staged YAML corpus
        load_company_bank(stage)
        
        companies_dir = bank_root / "companies"
        
        if not companies_dir.exists():
            os.replace(stage, companies_dir)
            return ImportResult(
                status=ImportStatus.CREATED,
                company_count=len(dossiers),
                target=companies_dir
            )
            
        if _files_identical(stage, companies_dir):
            return ImportResult(
                status=ImportStatus.UNCHANGED,
                company_count=len(dossiers),
                target=companies_dir
            )
            
        raise CompanyBankValidationError("import would overwrite modified or different companies directory")
        
    finally:
        if stage.exists():
            import shutil
            shutil.rmtree(stage)
