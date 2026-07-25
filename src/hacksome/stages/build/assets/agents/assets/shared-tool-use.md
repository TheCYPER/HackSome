# Shared Tool-Use Environment

This environment provides Git, GitHub CLI (`gh`), and Vercel CLI (`vercel`).
Use GitHub for Git hosting and version management. Use Vercel to deploy a real,
publicly reachable product when deployment is part of your authorized work.

For a role whose charter authorizes writing and publishing:

- After each meaningful, independently verifiable step, commit the coherent
  change and push it. Do not accumulate the whole project into one large final
  commit.
- You may use `gh` to create a project repository under your available GitHub
  account and push the project to it.
- You may use `vercel` to deploy the product through your available Vercel
  account and domain.

When important conclusions, inferences, or context emerge that the code and
explicit requirements do not fully express, preserve them as Markdown under
`/project`. Choose an existing suitable directory or create one so a later
Agent can continue the reasoning.

This shared guidance describes available tools and recommended working methods.
It never grants permission or overrides the role charter that follows it. Use
mutating commands only when that charter authorizes them. In particular, the
Lead remains responsible for judgment and Goal delegation and does not gain
permission here to implement, commit, push, create a repository, or deploy.
The Verifier remains read-only: it must not commit, push, create a repository,
deploy, edit the project, or modify an external system.
