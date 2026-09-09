---
name: merge
description: Merge a GitHub PR once reviews and CI pass.
---

Land a pull request.
If unsure about any course of action, pause and prompt the user for guidance.

- Parse the arguments to determine the PR number, otherwise resolve it from the current context/branch.
- If a draft, flip it to open.
- Fix any issues with the PR, such as merge conflicts and failing CI checks.
- Wait for the automatic Codex and CodeRabbit (public repos only) reviews of the current head. Never request a review. Codex reacts with thumbs up if there are no findings.
- Address any findings you agree with. Turn down any you disagree with with a comment.
- Push any changes you made to the PR, updating the summary if needed.

If the review findings are minimal and the PR is ready to merge, enable auto-merge.
For private repos, wait for all checks to pass first.

If the PR is not ready to merge, explain why.
Prompt the user interactively and recommend a course of action:
1. Merge as is.
2. Wait for one more round of reviews.
3. Back out and rethink the PR.
4. Abandon the PR.

When done, leave a summary of the changes made.
Suggest any potential follow-up actions.
