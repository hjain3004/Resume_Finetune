# Top 40 Shortlisted Jobs

This directory contains the top 40 shortlisted jobs scored from the latest ingestion batch.
It is staged for use with Codex on Chrome / GitHub.

## Contents
- `jobs_top40.db`: Standalone SQLite database (contains schema + top 40 jobs + latest run).
- `jobs_top40.json`: Complete JSON export of all 40 jobs with scores, rationales, and full JD texts.
- `jds/`: Individual plaintext JD files for each job, named by rank and company.

## Usage with Codex / Tailoring Lane
- **Direct file tailoring:**
  ```bash
  python -m scripts.tailor_now run --jd shortlist/jds/<file>.txt --company "<Company>" --title "<Title>" --variant <variant>
  ```
- **Using as pipeline database:**
  ```bash
  mkdir -p data && cp shortlist/jobs_top40.db data/jobs.db
  ```

## Shortlist Table

| # | Score | Company | Title | Variant | Location | File |
|---|---|---|---|---|---|---|
| 1 | 9.5 | Zoom | Software Development Engineer | backend | San Jose, CA | [`01_Zoom_Software_Development_Engineer.txt`](jds/01_Zoom_Software_Development_Engineer.txt) |
| 2 | 9.0 | DoorDash | Software Engineer 1 - Entry-Level | backend | Seattle, WA; SF; LA; NYC; Sunnyvale, CA | [`02_DoorDash_Software_Engineer_1_Entry_Level.txt`](jds/02_DoorDash_Software_Engineer_1_Entry_Level.txt) |
| 3 | 9.0 | TikTok | Software Engineer, Global CRM Platform | backend | San Jose, CA, United States | [`03_TikTok_Software_Engineer_Global_CRM_Platform.txt`](jds/03_TikTok_Software_Engineer_Global_CRM_Platform.txt) |
| 4 | 9.0 | TikTok | Backend Software Engineer Graduate (Global E-commerce) - 2027 Start | backend | San Jose, CA, United States | [`04_TikTok_Backend_Software_Engineer_Graduate_Globa.txt`](jds/04_TikTok_Backend_Software_Engineer_Graduate_Globa.txt) |
| 5 | 9.0 | TikTok | Backend Software Engineer Graduate (Creation Platform) - 2027 Start | backend | San Jose, CA, United States | [`05_TikTok_Backend_Software_Engineer_Graduate_Creat.txt`](jds/05_TikTok_Backend_Software_Engineer_Graduate_Creat.txt) |
| 6 | 9.0 | TikTok | Backend Software Engineer Graduate (Global E-commerce) - 2027 Start | backend | Seattle, WA, United States | [`06_TikTok_Backend_Software_Engineer_Graduate_Globa.txt`](jds/06_TikTok_Backend_Software_Engineer_Graduate_Globa.txt) |
| 7 | 9.0 | TikTok | Backend Software Engineer Graduate (TikTok - Data Lifecycle Management) - 2027 Start | backend | San Jose, CA, United States | [`07_TikTok_Backend_Software_Engineer_Graduate_TikTo.txt`](jds/07_TikTok_Backend_Software_Engineer_Graduate_TikTo.txt) |
| 8 | 9.0 | ID.me | Software Development Engineer New Grad | backend | Mountain View, CA | [`08_ID_me_Software_Development_Engineer_New_Grad.txt`](jds/08_ID_me_Software_Development_Engineer_New_Grad.txt) |
| 9 | 8.5 | RoadRunner | Forward Deployed Engineer New Grad | backend | SF | [`09_RoadRunner_Forward_Deployed_Engineer_New_Grad.txt`](jds/09_RoadRunner_Forward_Deployed_Engineer_New_Grad.txt) |
| 10 | 8.5 | LexisNexis Legal & Professional | Software Engineer 1 - Aspire Graduate Program | backend | Raleigh, NC | [`10_LexisNexis_Legal_Professional_Software_Engineer_1_Aspire_Graduate_Prog.txt`](jds/10_LexisNexis_Legal_Professional_Software_Engineer_1_Aspire_Graduate_Prog.txt) |
| 11 | 8.5 | OpenAI | Software Engineer - Applied Emerging Talent | backend | SF | [`11_OpenAI_Software_Engineer_Applied_Emerging_Talen.txt`](jds/11_OpenAI_Software_Engineer_Applied_Emerging_Talen.txt) |
| 12 | 8.5 | C3.ai | Platform Full-Stack Engineer New Grad | backend | Redwood City, CA | [`12_C3_ai_Platform_Full_Stack_Engineer_New_Grad.txt`](jds/12_C3_ai_Platform_Full_Stack_Engineer_New_Grad.txt) |
| 13 | 8.5 | Commure | Software Engineer - Early Career | backend | LA; Mountain View, CA | [`13_Commure_Software_Engineer_Early_Career.txt`](jds/13_Commure_Software_Engineer_Early_Career.txt) |
| 14 | 8.5 | KLA | AI Software Engineer - Manufacturing | backend | Ann Arbor, MI | [`14_KLA_AI_Software_Engineer_Manufacturing.txt`](jds/14_KLA_AI_Software_Engineer_Manufacturing.txt) |
| 15 | 8.5 | Yext | Software Engineer | backend | New York, NY, United States | [`15_Yext_Software_Engineer.txt`](jds/15_Yext_Software_Engineer.txt) |
| 16 | 8.5 | Huntington National Bank | Junior Backend Java Developer- Enterprise Payments and Credit Card | backend | Minnetonka, MN, United States | [`16_Huntington_National_Bank_Junior_Backend_Java_Developer_Enterprise.txt`](jds/16_Huntington_National_Bank_Junior_Backend_Java_Developer_Enterprise.txt) |
| 17 | 8.5 | NetApp | Entry Level Software Engineer - ANF (Azure NetApp Files) | backend | San Jose, CA, United States | [`17_NetApp_Entry_Level_Software_Engineer_ANF_Azure_.txt`](jds/17_NetApp_Entry_Level_Software_Engineer_ANF_Azure_.txt) |
| 18 | 8.5 | NetApp | Entry Level Software Engineer - ANF (Azure NetApp Files) Job Details / NetApp, Inc. | backend | San Jose, CA, United States | [`18_NetApp_Entry_Level_Software_Engineer_ANF_Azure_.txt`](jds/18_NetApp_Entry_Level_Software_Engineer_ANF_Azure_.txt) |
| 19 | 8.5 | Verkada | Backend Engineer - Connectivity | backend | San Mateo, CA, United States | [`19_Verkada_Backend_Engineer_Connectivity.txt`](jds/19_Verkada_Backend_Engineer_Connectivity.txt) |
| 20 | 8.5 | Roblox | Software Engineer, Creator Business | backend | San Mateo, CA, United States | [`20_Roblox_Software_Engineer_Creator_Business.txt`](jds/20_Roblox_Software_Engineer_Creator_Business.txt) |
| 21 | 8.5 | TikTok | Software Engineer Graduate(Ads Infrastructure) - 2027 Start | backend | San Jose, CA, United States | [`21_TikTok_Software_Engineer_Graduate_Ads_Infrastru.txt`](jds/21_TikTok_Software_Engineer_Graduate_Ads_Infrastru.txt) |
| 22 | 8.5 | TikTok | Software Engineer, TikTok LIVE - Foundation - Governance | backend | San Jose, CA, United States | [`22_TikTok_Software_Engineer_TikTok_LIVE_Foundation.txt`](jds/22_TikTok_Software_Engineer_TikTok_LIVE_Foundation.txt) |
| 23 | 8.5 | TikTok | Software Engineer, TikTok LIVE | backend | San Jose, CA, United States | [`23_TikTok_Software_Engineer_TikTok_LIVE.txt`](jds/23_TikTok_Software_Engineer_TikTok_LIVE.txt) |
| 24 | 8.5 | Giga | Software Engineer I / II | backend | New York, NY, United States | [`24_Giga_Software_Engineer_I_II.txt`](jds/24_Giga_Software_Engineer_I_II.txt) |
| 25 | 8.5 | TikTok | Software Engineer Graduate (Global E-commerce-Search) - 2027 Start | backend | Seattle, WA, United States | [`25_TikTok_Software_Engineer_Graduate_Global_E_comm.txt`](jds/25_TikTok_Software_Engineer_Graduate_Global_E_comm.txt) |
| 26 | 8.5 | IBM | Entry Level Software Developer-Tucson, AZ | backend | Tucson, AZ, United States | [`26_IBM_Entry_Level_Software_Developer_Tucson_AZ.txt`](jds/26_IBM_Entry_Level_Software_Developer_Tucson_AZ.txt) |
| 27 | 8.5 | ID.me | Summer 2027- Software Development Engineer - New Grad | backend | Mountain View, CA, United States | [`27_ID_me_Summer_2027_Software_Development_Enginee.txt`](jds/27_ID_me_Summer_2027_Software_Development_Enginee.txt) |
| 28 | 8.5 | TikTok | Software Engineer Graduate (TikTok Global Live) - 2027 Start | backend | San Jose, CA, United States | [`28_TikTok_Software_Engineer_Graduate_TikTok_Global.txt`](jds/28_TikTok_Software_Engineer_Graduate_TikTok_Global.txt) |
| 29 | 8.5 | Infosys | Java Backend Developer | backend | Boston, MA, United States | [`29_Infosys_Java_Backend_Developer.txt`](jds/29_Infosys_Java_Backend_Developer.txt) |
| 30 | 8.5 | AiPrise | Software Engineer 1 | backend | San Jose, CA | [`30_AiPrise_Software_Engineer_1.txt`](jds/30_AiPrise_Software_Engineer_1.txt) |
| 31 | 8.5 | Arch | Software Engineer - Early Careers | backend | NYC | [`31_Arch_Software_Engineer_Early_Careers.txt`](jds/31_Arch_Software_Engineer_Early_Careers.txt) |
| 32 | 8.5 | Motorola | Applied AI Engineer 1 - Supply Chain | backend | Chicago, IL | [`32_Motorola_Applied_AI_Engineer_1_Supply_Chain.txt`](jds/32_Motorola_Applied_AI_Engineer_1_Supply_Chain.txt) |
| 33 | 8.5 | Expedia Group | Software Development Engineer 1 | backend | Seattle, WA | [`33_Expedia_Group_Software_Development_Engineer_1.txt`](jds/33_Expedia_Group_Software_Development_Engineer_1.txt) |
| 34 | 8.5 | Valon | Software Engineer New Grad | backend | SF; NYC | [`34_Valon_Software_Engineer_New_Grad.txt`](jds/34_Valon_Software_Engineer_New_Grad.txt) |
| 35 | 8.5 | Stripe | Software Engineer New Grad | backend | Seattle, WA; SF; NYC | [`35_Stripe_Software_Engineer_New_Grad.txt`](jds/35_Stripe_Software_Engineer_New_Grad.txt) |
| 36 | 8.5 | Notion | Software Engineer, Early Career | backend | San Francisco, California | [`36_Notion_Software_Engineer_Early_Career.txt`](jds/36_Notion_Software_Engineer_Early_Career.txt) |
| 37 | 8.5 | ByteDance | Graduate Software Engineer - Dev Infra | backend | San Jose, CA | [`37_ByteDance_Graduate_Software_Engineer_Dev_Infra.txt`](jds/37_ByteDance_Graduate_Software_Engineer_Dev_Infra.txt) |
| 38 | 8.5 | NewsBreak | Newsbreak Venture New Grad - AI Growth Intelligence Engineer | backend | Mountain View, CA | [`38_NewsBreak_Newsbreak_Venture_New_Grad_AI_Growth_Int.txt`](jds/38_NewsBreak_Newsbreak_Venture_New_Grad_AI_Growth_Int.txt) |
| 39 | 8.5 | Notion | Software Engineer – Early Career | backend | SF | [`39_Notion_Software_Engineer_Early_Career.txt`](jds/39_Notion_Software_Engineer_Early_Career.txt) |
| 40 | 8.5 | Notion | Software Engineer – Early Career - AI | backend | SF | [`40_Notion_Software_Engineer_Early_Career_AI.txt`](jds/40_Notion_Software_Engineer_Early_Career_AI.txt) |
