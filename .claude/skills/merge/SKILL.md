---
name: merge
description: Merge a GitHub PR once reviews and CI pass.
---

Land a pull request.
If unsure about any course of action, pause and prompt the user for guidance.

- Parse the arguments to determine the PR number, otherwise resolve it from the current context/branch.
- If a draft, flip it to open.
- Fix any issues with the PR, such as merge conflicts and failing CI checks.
- Wait for a recent, automated Codex and CodeRabbit (public repos only) review. Codex reacts with thumbs up if there are no findings.
- Address any findings you agree with. Turn down any you disagree with with a comment.
- Push any changes you made to the PR, updating the summary if needed, and repeat the review process.
- On private repos, do not rely on auto-merge to gate CI; wait until all CI checks pass before enabling it.
- Enable auto-merge if the PR is ready.
- When the PR is merged, leave a summary of the changes made and any potential follow-up actions.
