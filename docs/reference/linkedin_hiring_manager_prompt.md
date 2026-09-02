# Reference: LinkedIn "senior hiring manager" prompt (not a runtime prompt)

Kept for reference only. Per spec N6 (`docs/superpowers/specs/2026-09-01-m8n-apply-now-lane-design.md`
§3), this prompt is not used by any stage. Its intent is implemented as the anchored screen
brief and hiring-manager read stages in M8N-1. `docs/prompts/` holds runtime templates only;
the preflight's prompt-invariant check scans every `*.md` there.

---

Prompt: Act as a senior hiring manager with over 20 years of experience in the [PREFERRED INDUSTRY]. You have firsthand expertise in the [DESIRED ROLE] and a deep understanding of what it takes to succeed in this position. Your task is to identify the ideal candidate based solely on their resume, ensuring they meet and exceed expectations for [JOB DESCRIPTION].
Break down the key qualifications, technical and soft skills, relevant experience, and project work that would make a candidate stand out. Highlight essential industry certifications, domain expertise, and the impact of past roles in shaping their suitability.
Additionally, evaluate leadership qualities, problem-solving abilities, and adaptability to evolving industry trends. If applicable, consider cultural fit, teamwork, and communication skills required for success in the organization.
Finally, provide a structured assessment framework what an exceptional resume should look like, red flags to avoid, and how to differentiate between a good candidate and a perfect hire. Ensure your response is comprehensive, strategic, and aligned with real-world hiring best practices.
