# Where chatgpt-voice lived (before moving to its own repo)

## What was committed

- **Repository:** `clawd` (github.com/Koprowski/clawd)
- **Committed path:** The entire `chatgpt-voice/` **subfolder** inside clawd.
- So the published source was: **clawd repo → `chatgpt-voice/`** (e.g. `e:\OneDrive\Apps\clawd\chatgpt-voice\` on your machine).

## Two directories on your machine

| Location | Role | Version control |
|----------|------|-----------------|
| **e:\OneDrive\Apps\clawd\chatgpt-voice\** | Source inside the clawd repo. This is what got committed when you pushed clawd. | Yes — part of clawd (main branch). |
| **C:\Tools\chatgpt-voice\** | Where you actually run the app (venv, `python -m chatgpt_voice start`). | No — outside clawd. A separate folder we kept in sync by copying files. |

So: **clawd** = the repo that contained chatgpt-voice as a subfolder. **C:\Tools\chatgpt-voice** = your install/run location, not part of that repo. Edits were made in clawd’s copy (or the workspace), then copied to C:\Tools (and into the venv) so the running app matched.

## After moving to its own repo

- **New repo:** `chatgpt-voice` (standalone repository).
- You can clone it to `C:\Tools\chatgpt-voice` (or anywhere) and use that as the single source of truth — no more copying from clawd.
- **clawd** will no longer contain a `chatgpt-voice/` folder.
