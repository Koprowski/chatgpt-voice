# ChatGPT Voice Agent Instructions

This repo is Jason's system-wide voice dictation tool. It is an active daily-use productivity enabler in Mission Control.

Read README.md, IMPLEMENTATION_GUIDE.md, and LEGAL.md as needed before making behavior or packaging changes.

## Planning System: Mission Control vs GitHub

`MC` means Mission Control.

Canonical Mission Control repo:

- GitHub: `Koprowski/mission-control`
- Local Windows path: `E:\Apps\mission-control`

Mission Control/WBS is the master portfolio map across projects. It is not only
committed execution. It is also the visibility layer for candidate leverage:
active work, shaped backlog, discovery items, and high-leverage opportunities
that should compete for attention across projects.

GitHub Issues are the canonical source of truth for repo-specific implementation
detail: PRDs, epics, bugs, reviews, acceptance criteria, and engineering
follow-ups.

When a new repo-tied idea appears:

- If it may affect prioritization, add or recommend a Mission Control/WBS item.
- If it needs product or engineering definition, create or recommend a GitHub
  issue.
- If both are true, do both: create the GitHub issue for detail and add a
  Mission Control/WBS line that links to it.
- Do not treat "not fully shaped" as a reason to omit it from Mission Control.
  Instead mark it as `Discovery/Shaping`.
- Do not treat Mission Control as the place for detailed specs. Keep detailed
  specs in the linked repo artifact.

Planning states:

- `Opportunity`: worth tracking, not yet shaped.
- `Discovery/Shaping`: likely valuable, needs scope and acceptance criteria.
- `Ready`: scoped enough to implement.
- `Active`: currently being worked.
- `Done/Parked`: completed or intentionally deferred.

Command shortcuts:

- `Capture this to MC` / `Capture to MC`: update the appropriate Mission
  Control surface, and capture to OpenBrain when the item should be searchable
  later.
- `MC what changed?`: summarize the latest Mission Control digest and relevant
  repo activity.
- `MC what next?`: recommend the next useful action from Mission Control current
  state, WBS, and recent activity.
- `MC session audit`: summarize this session into Mission Control and OpenBrain.

Decision shortcut:

1. Ask whether the item is repo-tied, cross-project, or personal/process.
2. For repo-tied work, prefer GitHub Issues for implementation detail.
3. For anything that should compete for attention or resources, also put it in
   Mission Control.
4. If uncertain, capture it in Mission Control as `Discovery/Shaping` rather
   than letting it disappear.

Agent behavior:

- When updating Mission Control from another repo, preserve unrelated local work
  in both repos.
- If filesystem permissions block direct edits to `E:\Apps\mission-control`,
  ask for permission rather than writing Mission Control content into the
  current repo.
- After meaningful Mission Control changes, commit and push the Mission Control
  repo unless the user asks not to.