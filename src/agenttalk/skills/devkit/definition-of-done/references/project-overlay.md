---
reviewed-against: "0.102"
---

# Project overlay for the definition of done

In plain words: the base and the profiles are the same for every project. What only your
project needs goes in one short file that your project owns, for example
`docs/DEFINITION-OF-DONE-OVERLAY.md`. The lead points the task at it. An overlay can add
rows and name people; it cannot remove or weaken a base or profile row.

## Shape
```
policy: definition-of-done@1
maintainer: <a named person or seat>
exception authority: <a named person or seat; not the doer of the task>
delivery: <how every seat gets the pinned text and this overlay: the repository, the
          release tag, and how a seat checks the identity it read>

added rows (per profile):
  <profile>: <row>, <what proves it>

project rules that apply to every task:
  <isolation or offline rule, branch rule, hosts or accounts that are never touched,
   a named tool and its settings, a vendor that may not be the only reader,
   how many review rounds a slice gets and what happens to a P1 found late, ...>

change log:
  <date> <what changed> <who reviewed it>
```

## Identity of an overlay
The overlay is a committed file. A task pins it by repository, path and the git blob id (or
commit id) of the file at assignment, written in the task, never inside the file itself
(`overlay: <repository> <path> blob <id>`). Any edit is a new identity, so a running task
keeps the overlay it was assigned under, and a reader can fetch exactly that text with
`git show <blob id>`. An overlay that cannot be fetched at its recorded identity is an
unresolved pin: see PINNING in `../SKILL.md`.

## Rules for the overlay
- A rule that comes from a lesson is proposed to the maintainer and takes effect only after
  they accept it and write it in the change log. No rule appears automatically.
- A rule that must start applying to a task that is already running is an urgent safety
  change: the maintainer says so in writing, with the reason, in the task.
- Name any row that cannot ever be not applicable in this project, and say why.
- Put no secrets, private addresses or customer names in it. Refer to secrets by location.
