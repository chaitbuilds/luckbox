# Setting up luckbox

About 30 minutes, most of it writing about yourself.

## 1. Requirements

- Python 3.9+ (standard library only).
- [Claude Code](https://claude.com/claude-code), logged in (`claude` works in your terminal). A subscription
  or an API key both work; luckbox calls it headlessly.
- macOS or Linux.

## 2. Init

```sh
python3 -m luckbox init
```

It asks your name, email addresses (so your own mail isn't a contact), city, what counts as nearby, and
timezone, then creates:

```
~/.luckbox/                never in git
  config.json              sources, home, models, brief size
  exclude.txt              people never to index
  people/decisions.tsv     who you know and how
  people/routers.md        people close to you who can open a world
  radars/                  one JSON file per interest
~/luckbox-profile/         markdown about you; make it a private git repo
  me.md  now.md  interests/
```

## 3. Write your profile

This is what makes it yours. The judge reads it for every item.

- **me.md**: who you are, your priorities in order, constraints, where you live, how you want suggestions written.
- **now.md**: this month's focus and what you're looking for. Two minutes whenever it changes.
- **interests/*.md**: one file per interest: the questions you're working on, who's worth meeting, what to skip.
- A heading containing **Private** marks background the judge may use but never mention.

Be specific. "AI" gets you noise; "which proactive actions people accept from an agent" gets you the three
papers and the one meetup that matter.

## 4. Draft radars

```sh
python3 -m luckbox radar draft ~/luckbox-profile/interests/<interest>.md
```

Claude searches the web for real sources (feeds, arXiv categories, researchers, Luma calendars, events
pages near you), checks the links, and writes `~/.luckbox/radars/<interest>.json`. Read it, cut what looks
off, then:

```sh
python3 -m luckbox fetch --radar <interest> && python3 -m luckbox judge --radar <interest>
```

Useful radar fields: `weight` (orders radars), `min_score`, `max_per_day`, `max_per_kind`
(e.g. `{"paper": 2, "event": 3}`), `fresh_days`, `every_days` (a weekly radar), and `guidance` (a few
sentences on what a great move is). Context refs: `profile:<path>`, `local:<path>` (inside `~/.luckbox`),
`people:core`.

Built-in radar ideas: **telling** (`{"type": "telling", "repos": ["~/code/project"]}`), a weekly
**wildcard** from local events, and **people** (`{"type": "people_scout"}` plus `{"type": "followups"}`).

## 5. People (optional, recommended)

luckbox learns who you actually know from exports, never live access:

- **Google Takeout** (Mail, mbox) → `{"name": "mail", "type": "mbox", "path": "archives/takeout.zip"}`.
  Headers only. Then `python3 -m luckbox snapshot mail` reduces it to a few KB and you can delete the archive.
- **LinkedIn** data export → `{"name": "linkedin", "type": "linkedin", "path": "archives/linkedin.zip"}`
  (a lookup table, not a list of friends).

```sh
python3 -m luckbox ingest     # keeps only people where both sides actually wrote
python3 -m luckbox review     # writes a list of people without a decision
python3 -m luckbox decide someone@example.com keep mentor "reviewed my deck"
```

Put anyone who should never be indexed in `exclude.txt` first.

## 6. Every morning

```sh
python3 -m luckbox schedule --hour 6 --minute 30
```

macOS: two launchd jobs (the daily run, and the page at http://127.0.0.1:8765/). Build the notifier
with `macos/build.sh` so clicking the notification opens your list. Linux: two cron lines and `notify-send`.

## 7. Using the list

`j`/`k` move · `space` details · `o` open · `g` keep · `d` done · `r` replied · `x` dismiss.
Untouched moves leave after 10 days; events leave once they've happened. Your recent marks are shown to
the judge as examples, so dismissing junk is how it learns.
