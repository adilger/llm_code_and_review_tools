---
name: release-priority
description: This skill should be used to see where a Lustre release's priority patches and blockers stand and what an engineer can do to get them landed, with the release-priority CLI and their own Gerrit login - "what's at 2.18 release priority", "what do I need to do for the release", "how can I help get 2.18 out", "which release patches need review", "what are the release blockers", "are any of my patches holding up the release", "what am I reviewing for 2.18", "what's in master-next", "why is this release patch stuck", "218_review_priority", "218_review_blocker". Covers the commands, the statuses and whose move each is, and how to turn the JSON into a clear status page with links.
version: 0.2.0
---

# Release priorities: what is holding up the release, and how to help

A Lustre release's **priority changes** are the open Gerrit changes
carrying its hashtag: `218_review_priority` for 2.18 (the release number
without dots, plus `_review_priority`).  Its **blockers** carry
`218_review_blocker` (`_review_blocker`), with or without the priority
tag; they hold up the release, and come first everywhere.
`release-priority` gives each change a status and says whose move it
is, and for the engineer running it, what is theirs to do and where they
can help.

The same changes are on a public web page, rebuilt every minute:
**https://mulberrytree.us/release_priority/**.  Point the engineer there
for the whole picture; the CLI is for their own part of it.  For 2.18
the CLI reads that page's `data.json` (about a second); for other
releases, with `--live`, or when the page is down or more than 15
minutes old, it reads Gerrit itself (a few seconds).  `source` in the
output says which.

Output is JSON, the data payload by default; `--envelope` gives
`{ok, data, meta, next_actions}`.  Read the JSON; do not pipe it through
`head`.  Errors are JSON and exit 2 (login), 3 (not found), 4 (bad
input), 5 (unreachable) or 1.

## Who you are

The login is gerrit-cli's (`~/.config/gerrit-cli/.env`, or `GERRIT_USER`
and `GERRIT_PASS`, the HTTP password from Gerrit's Settings > HTTP
Credentials).  It says who "me" is; `--user` picks another gerrit-cli
credential set.  `list`, `master-next` and `show` work without a login;
`me` needs one, or `--as LOGIN`.

```bash
release-priority whoami                 # your Gerrit account, the release and hashtag
```

## Commands

```bash
release-priority me                     # start here: what is yours, and where to help
release-priority me --master-next       # ... and the changes in master-next
release-priority me --as adilger        # someone else's view (username, email or id)
release-priority list                   # every priority change, grouped as the page
release-priority list -g review         # one group: review owner ci behind ready master_next
release-priority list --blockers        # only the release blockers
release-priority list --owner Dilger    # one owner's
release-priority master-next            # in master-next, and ready to land
release-priority show 69572             # one change: status, why, what to do
release-priority -r 2.17 list           # another release (its hashtags must exist)
release-priority me --live              # read Gerrit, not the page
```

### What `me` returns

| key | what |
|---|---|
| `blockers` | every release blocker: status, whose move, `yours`, `you_review` |
| `your_move` | your changes that need you, each with `action` and `commands` |
| `your_changes_in_review` | yours waiting on reviewers; nothing to fix, ping if they sit |
| `reviews_owed` | changes you review that wait on your vote |
| `needs_review` | the other priority changes needing review, fewest reviewers first, with `reviewer_count` and `you_are_reviewer` |
| `your_other_changes` | yours in CI, behind, ready or in master-next: nothing to do |
| `master_next` | with `--master-next` only |
| `suggestions` | one-line next steps, most pressing first |
| `counts`, `web_page` | the totals, and the page's URL |

Every list puts blockers first.  Each change has `n`, `url`, `subject`, `ticket`, `ticket_url`, `owner`,
`status`, `why`, `whose_move`, `reviewers` (name and vote), `plus` of
`need` +1s, `unresolved`, `ci`, `quiet_days` (since a person last spoke)
and, when they apply, `behind` (the change holding it back) and
`release_blocker`.

## Presenting it

The engineer wants a status page, not JSON.  Write it as:

1. **One line of where things stand**: the counts (`counts`), and the web
   page link: "51 open priority changes: 8 need review, 19 wait on their
   owners, 4 in master-next.  Full list: <https://mulberrytree.us/release_priority/>".
2. **Blockers**, when there are any (`blockers`): each as a link with
   its status and whose move, marking the ones that are theirs or that
   they review.  Say plainly that these hold up the release.
3. **Yours to do** (`your_move`, then `reviews_owed`), most pressing
   first.  One line each, with the change as a link and the action:
   `- [62868](https://review.whamcloud.com/c/fs/lustre-release/+/62868) LU-12187 llite: enable FLR EC support: Reviewer -1, answer the -1 from Marc Vef`.
   Offer the `commands` as how to do it.
4. **Yours, waiting on others** (`your_changes_in_review`,
   `your_other_changes`): brief; say who has the move.
5. **Where you can help** (`needs_review`): the changes needing review
   as links, with `plus`/`need` and the reviewer count, those with no
   reviewers or no +1s first.  Any +1 from someone other than the owner
   helps; two are needed on master.
6. The `suggestions`, in your own words.  Mark blockers in every list
   (**Blocker**).

Every change number is a markdown link to its `url`, and every ticket to
its `ticket_url`.  Leave out what is empty rather than printing "none"
sections.  When nothing is theirs, say so and go straight to where they
can help.

## Statuses, and whose move

The first rule that applies wins; the web page and the Gerrit Tracker use
the same rules.

| status | means | group | whose move |
|---|---|---|---|
| In master-next | queued for landing | master_next | the gatekeeper |
| Behind N | change N earlier in the series has a failure | behind | nobody: fix N |
| Work in progress | marked WIP | owner | owner |
| Build failed | Jenkins failed the latest patchset | owner | owner |
| Needs rebase | checkpatch: cannot be cherry-picked | owner | owner |
| Tests failed | enforced failures, no retest asked | owner | owner |
| Janitor failures | failures unique to this patch | owner | owner |
| Verified -1 | from someone other than CI | owner | owner |
| Reviewer -1 | a person voted -1 or -2 | owner | owner |
| Checkpatch -1 / Robot -1 | style or a review robot | owner | owner |
| Retest pending | every enforced failure has a retest asked | ci | CI |
| In CI | no build or test verdict yet | ci | CI |
| Needs reviewers | fewer than 2 (1 off master) human reviewers | review | owner (add reviewers) |
| Comments to answer | short of +1s, unresolved comments, last word not the owner's | owner | owner |
| Waiting on review | short of +1s | review | the reviewers who have not voted |
| Ready to land | reviewed, built, Maloo +1 | ready | the gatekeeper |

## Doing the work

- Review comments and replies: the `gerrit-patch-workflow` skill (`gc comments N`, `gc review N`).
- Failed tests: `gc maloo N`, or the `lustre-ci-triage` skill, to tell
  the patch's own failures from known ones before retesting.
- Having the Patch Watcher bot retest or find reviewers for you:
  `pw-cli retest N`, `pw-cli reviewers N` (the `pw-cli` skill).  Offer
  these; do not run them unasked.

The tool only reads.  It never votes, comments or changes a hashtag.
Marking a change a blocker is a release manager's call, made in Gerrit
(`gc hashtag N --add 218_review_blocker`); do not tag changes unasked.
