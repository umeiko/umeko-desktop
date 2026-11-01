---
name: dogfood
description: 'Exploratory QA of web apps: find bugs, evidence, reports.'
license: MIT
metadata:
  hermes:
    tags:
    - qa
    - testing
    - browser
    - web
    - dogfood
    related_skills: []
  version: 1.0.0
  author: Teknium (teknium1), Hermes Agent
  platforms:
  - linux
  - macos
  - windows
---
> Umeko adaptation, 2026-11-01. Use Pi Agent's available `read`, `write`,
> `edit` and `bash` tools rather than another harness's tool names. Resolve
> helper and reference paths from this SKILL.md directory; write deliverables
> in the user's task workspace. Show finished artifacts with
> `submit_to_chatbox` tool (consult its actual tool schema).
> Dependencies below are prerequisites, not a claim that they are installed.

# Exploratory web app QA

Use an available browser automation tool or a task-local Playwright environment.
First inspect the actual tool schema; Umeko does not provide Hermes's
`browser_exec`, `cdp`, or Python browser helper globals. If no browser automation
is available, explain that limit and perform only the checks supported by the
available tools. Do not invent screenshots or interactive test results.

1. Confirm the target URL and requested scope. Use test data and avoid destructive
   account actions unless the user authorized them.
2. Explore the main user paths, keyboard interaction, empty/loading/error states,
   navigation, and layout at the viewport sizes relevant to the request.
3. For each defect, record the URL, viewport, exact reproduction steps, observed
   versus expected behavior, severity, and a screenshot where supported. Verify
   a second time to distinguish a repeatable defect from a transient failure.
4. Deduplicate issues by cause. Keep a separate list of untested areas and any
   missing credentials or browser capability.
5. Save a concise Markdown report in the task workspace and show it using
   `submit_to_chatbox`. Include only evidence actually observed.

Browser dependencies are optional: do not install or start an unrelated gateway
or Hermes runtime just to follow this Skill. The bundled report template is in
`templates/dogfood-report-template.md` if a more structured report is needed.
