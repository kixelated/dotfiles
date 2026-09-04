---
name: takeover
description: Adopt someone else's open PR and drive it to landable.
---

Someone else opened this PR; you are now responsible for it.
If unsure about any course of action, prompt the user for guidance.

- Parse the arguments to determine the PR number.
- Read the PR, any linked issues, reviews/comments posted on the PR, and the surrounding code.
- Judge the approach before touching anything. Would you try another different approach?
- Fix any issues with the PR, such as merge conflicts and failing CI checks.
- Address any automated review findings (Codex/CodeRabbit) you agree with. Turn down any you disagree with with a comment.
- Push any changes you made to the PR, updating the summary if needed.
- Summarize the changes made and any potential follow-up actions.
- No not merge the PR until a /pr-merge is approved.
