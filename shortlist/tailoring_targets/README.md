# Tailoring Targets: Top 10 Opportunities Across Unique Companies

This directory contains the curated, reviewable tailoring target set of exactly ten roles across ten unique companies, superseded from the raw 40-job export.

## Contents
- `targets.json`: Full manifest recording rank, scores, URLs, selection rationale, and collapsed duplicate IDs.
- `selection_audit.json`: Deterministic invariant verification report.
- `jds/`: Exactly ten authentic, ATS-quality job descriptions.

## Target Summary Table

| Rank | Score | Company | Title | Variant | Location | JD File |
|---|---|---|---|---|---|---|
| 1 | 9.5 | **Zoom** | Software Development Engineer | backend | San Jose, CA | [`01_Zoom_Software_Development_Engineer.txt`](jds/01_Zoom_Software_Development_Engineer.txt) |
| 2 | 9.0 | **DoorDash** | Software Engineer 1 - Entry-Level | backend | Seattle, WA; SF; LA; NYC; Sunnyvale, CA | [`02_DoorDash_Software_Engineer_1_Entry_Level.txt`](jds/02_DoorDash_Software_Engineer_1_Entry_Level.txt) |
| 3 | 9.0 | **ID.me** | Software Development Engineer New Grad | backend | Mountain View, CA | [`03_ID_me_Software_Development_Engineer_New_Grad.txt`](jds/03_ID_me_Software_Development_Engineer_New_Grad.txt) |
| 4 | 9.0 | **TikTok** *(Required)* | Backend Software Engineer Graduate (Global E-commerce) - 2027 Start | backend | San Jose, CA; Seattle, WA | [`04_TikTok_Backend_Software_Engineer_Graduate_Globa.txt`](jds/04_TikTok_Backend_Software_Engineer_Graduate_Globa.txt) |
| 5 | 8.5 | **RoadRunner** | Forward Deployed Engineer New Grad | backend | SF | [`05_RoadRunner_Forward_Deployed_Engineer_New_Grad.txt`](jds/05_RoadRunner_Forward_Deployed_Engineer_New_Grad.txt) |
| 6 | 8.5 | **LexisNexis Legal & Professional** | Software Engineer 1 - Aspire Graduate Program | backend | Raleigh, NC | [`06_LexisNexis_Legal_Professional_Software_Engineer_1_Aspire_Graduate_Prog.txt`](jds/06_LexisNexis_Legal_Professional_Software_Engineer_1_Aspire_Graduate_Prog.txt) |
| 7 | 8.5 | **OpenAI** | Software Engineer - Applied Emerging Talent | backend | SF | [`07_OpenAI_Software_Engineer_Applied_Emerging_Talen.txt`](jds/07_OpenAI_Software_Engineer_Applied_Emerging_Talen.txt) |
| 8 | 8.5 | **C3.ai** | Platform Full-Stack Engineer New Grad | backend | Redwood City, CA | [`08_C3_ai_Platform_Full_Stack_Engineer_New_Grad.txt`](jds/08_C3_ai_Platform_Full_Stack_Engineer_New_Grad.txt) |
| 9 | 8.5 | **Commure** | Software Engineer - Early Career | backend | LA; Mountain View, CA | [`09_Commure_Software_Engineer_Early_Career.txt`](jds/09_Commure_Software_Engineer_Early_Career.txt) |
| 10 | 8.0 | **Twitch** *(Required)* | Software Engineer I, Payments | backend | San Francisco, California, USA | [`10_Twitch_Software_Engineer_I_Payments.txt`](jds/10_Twitch_Software_Engineer_I_Payments.txt) |

## Methodology & Invariants
1. **Ten Unique Companies**: Every company appears exactly once. Additional opportunities for the same employer are collapsed into the top role.
2. **TikTok Reconciled & Collapsed**: Exactly one TikTok role is included: `Backend Software Engineer Graduate (Global E-commerce) - 2027 Start`. San Jose and Seattle location postings are treated as one opportunity; all other 8 TikTok roles in the top 40 are collapsed. Authentic employer JD resolved from `lifeattiktok.com` requisition `7668824169648097541` (7,137 characters).
3. **Twitch Payments Included**: Authenticated through official Amazon Jobs requisition `10502486` (`Software Engineer I, Payments`, 5,074 characters), replacing the earlier aggregator stub.
4. **ATS Quality Guarantee**: Zero aggregator summaries are permitted as tailoring targets. Every role is sourced from official ATS platforms (Greenhouse, Ashby, Workday, Amazon Jobs, LifeAtTikTok).
5. **Deterministic Tie-Breaking**: Ranks are ordered by `fit_score DESC`, verified `date_posted DESC`, then `job_id DESC`.

## Audit Status
- **Overall Verdict**: `PASS`
- **Targets Count**: `10`
- **Unique Companies**: `10`
- **Zero Aggregator JDs**: `True`
- **Hash Integrity**: `Verified`
