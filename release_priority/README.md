# release-priority

A Lustre release's priority changes in Gerrit, and what an engineer can
do to get them landed.

A release's priority changes are the open changes carrying its Gerrit
hashtag: `218_review_priority` for 2.18 (the release number without
dots, plus `_review_priority`).  Each gets one status and the people
whose move it is, by the same rules as the Gerrit Tracker and the public
page at https://mulberrytree.us/release_priority/.

```bash
release-priority whoami            # your Gerrit account, release, hashtag
release-priority me                # yours to do, and where you can help
release-priority me --as adilger   # someone else's view
release-priority list [-g review]  # every priority change, grouped
release-priority master-next       # in master-next, and ready to land
release-priority show 69572        # one change
release-priority -r 2.17 list      # another release
```

`me` returns `your_move` (your changes that need you, with an action and
the commands that help), `your_changes_in_review`, `reviews_owed`
(changes you review that wait on your vote), `needs_review` (the other
changes needing review), `your_other_changes` and `suggestions`.

The login is gerrit-cli's: `~/.config/gerrit-cli/.env`, or `GERRIT_URL`,
`GERRIT_USER` and `GERRIT_PASS`; `--user` picks another credential set.
Only `me` without `--as`, and `whoami`, need it.  The tool only reads.

Output is JSON (`--envelope` for the `{ok, data, meta, next_actions}`
wrapper).  The `release-priority` skill says how to turn it into a status
page for the engineer.

Installed by the top-level `install.sh`; it needs `gerrit_cli` from this
repository.
