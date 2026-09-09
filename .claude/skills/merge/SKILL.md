---
name: merge
description: Merge a GitHub PR once reviews and CI pass.
---

Land a pull request.
If unsure about any course of action, pause and prompt the user for guidance.

- Parse the arguments to determine the PR number, otherwise resolve it from the current context/branch.
- If a draft, flip it to "Ready for Review" and wait for automated reviews to complete.
- Fix any issues with the PR, such as merge conflicts and failing CI checks.

Wait for any automated reviews to complete.
If everything looks good, enable auto-merge.
For private repos, wait for all checks to pass first.

When done, leave a summary of the changes made.
Suggest any potential follow-up actions.
