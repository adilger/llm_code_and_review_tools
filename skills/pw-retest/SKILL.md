---
name: pw-retest
description: This skill should be used to have Patch Watcher (the Lustre Gerrit bot, @Patrickbot) retest or shepherd a Gerrit change with the pw-retest CLI, signed in with your own Gerrit login - "have the bot retest my patch", "get Patch Watcher to shepherd this change", "watch 12345 at retest", "is the bot watching this change", "stop the bot on my change", "halt the bot on this patch", "release my halt". Covers what retest and shepherd do, which changes they refuse, and what a Gerrit account may and may not do.
version: 0.1.0
---

# Patch Watcher retest and shepherd, by Gerrit login

Patch Watcher is the bot (`@Patrickbot` on review.whamcloud.com) that
watches Lustre changes. `pw-retest` asks it, as your Gerrit account, for the
two things anyone with a Gerrit account may have it do: **retest** a change
and **shepherd** it. It is the same as tagging the bot on the change with
`@Patrickbot watch retest` or `watch shepherd`, without writing a comment,
and nothing is posted on the change.

```bash
pw-retest whoami                 # your account, as the bot sees it
pw-retest status 69157           # watched? at what level? halted?
pw-retest retest 69157           # watch at retest
pw-retest shepherd 69157 69158   # watch at shepherd, several at once
pw-retest stop 69157             # stop watching, and stop its run
pw-retest halt 69157 owner is reworking this
pw-retest clear-halt 69157 --note "rework uploaded"
```

A change is a number or any Gerrit URL for it. Output is JSON on stdout;
`--envelope` gives `{ok, data, meta}`. Exit codes: 0 done; 1 refused or
failed (the error's `code` says which: `NOT_AUTHORIZED`, `CONFLICT`,
`RATE_LIMITED`, `SERVER_ERROR`); 2 the login is missing or Gerrit refused
it; 3 no such change; 4 bad arguments; 5 Patch Watcher could not be
reached. With several changes, one refusal does not stop the rest: each
result is in the list, a refused one as `{"change", "error"}`, and the exit
code is the first refusal's.

## The login

It uses gerrit-cli's credentials: `GERRIT_USER` and `GERRIT_PASS` from the
environment or `~/.config/gerrit-cli/.env`, and `--user SET` picks another
credential set there, as with `gerrit --user`. The password is the Gerrit
**HTTP** password (Gerrit: Settings > HTTP Credentials), not a single
sign-on one. Patch Watcher checks it with Gerrit on every new login and
remembers a good one for ten minutes; it never stores the password.

If `whoami` says `AUTH_FAILED`, the HTTP password is wrong or has been
regenerated: fix the `.env`, do not retry in a loop. After five refused
logins for one name in fifteen minutes the server stops asking Gerrit and
answers `RATE_LIMITED` until the quarter hour is up.

`PW_RETEST_URL` points it at another Patch Watcher; the default is
`https://patchwatcher.mulberrytree.us`. It must be https (or loopback),
since the Gerrit password goes with every request.

## What the levels do

- **retest**: retests enforced CI failures that are linked to an existing
  LU ticket, and sends any failure no ticket covers to an AI run, which
  links and retests a known failure, files a ticket for one that is not the
  change's own, and reports on the rest. It never uploads to the change.
- **shepherd**: retest, and once CI passes, if fewer people are reviewing
  than the change needs votes, adds reviewers, pings the ones who have not
  voted at 7 and 21 days, and adds a second set after 14 quiet days. It
  never uploads to the change.

Retest and shepherd are refused (`CONFLICT`, code `level_refused` in
`details.server_code`, and the message says why) on a change that is not
meant to land as it stands: more than five deep in its series of open
changes, against LU-0000, or marked `fortestonly` or `forbuildonly` in
`Test-Parameters`. Do not retry those; the change has to change first.

Higher levels (smallfix, bigfix, own: the bot uploads fixes) are not
available here. They take a Patch Watcher tagger or admin, by tagging the
bot on Gerrit.

## Who may do what

Anyone with a Gerrit account may:

- watch a change at retest or shepherd, or move it between the two, as
  long as nobody set it higher; raising someone else's change from retest
  to shepherd is fine;
- stop watching, lower, or halt a change **they** had the bot watch, and
  release a halt they set.

People whose Gerrit email is at ddn.com or whamcloud.com may also lower or
stop a change someone else had watched at shepherd or below. `whoami`
shows this as `may_stop_others`.

Refusals worth knowing before trying:

- `CONFLICT` with `server_code: out_of_reach`: the change is watched above
  shepherd. This tool never touches such a change, whoever you are. Leave
  it, or tag the bot on Gerrit.
- `NOT_AUTHORIZED`: lowering, stopping or halting a change someone else had
  watched, or releasing someone else's halt. Ask whoever watched it.
- `RATE_LIMITED` with `server_code: daily_limit`: at most 30 changes newly
  watched a day per person this way. Changing the level of a change already
  watched does not count.
- `CONFLICT` with `server_code: closed`: the change is merged or abandoned.

## Judgment

- Check `status` first when you do not know whether the change is watched:
  a change already at shepherd needs nothing, and one at bigfix is out of
  reach.
- Watch what you mean to land. Retest on a change that is going to be
  reworked anyway spends CI on results nobody reads; halt or stop it
  instead.
- `halt` needs a reason a person will understand later ("owner reworking
  the locking, do not retest"). A halt stops the change's run and keeps the
  bot off it until released; `stop` takes it off the watch list.
- To find out why a test failed, or to have the bot change code, this is the
  wrong tool: use the CI triage tools, or ask a Patch Watcher tagger.
