# luckbox

A local engine that widens your luck surface area.

![Luck surface area: doing on one axis, telling on the other](https://www.codusoperandi.com/posts/images/luck-surface-area.png)

*Diagram: Jason Roberts, [Increase Your Luck Surface Area](https://www.codusoperandi.com/posts/increasing-your-luck-surface-area) (2010).*

## Luck surface area

Jason Roberts coined the term in 2010. The amount of luck you get is proportional to how much you do
something you care about, times how many people know about it:

**Luck = Doing × Telling**

Luck is the area of the rectangle. Do more and it grows. Tell more people and it grows. If either side
is zero, so is the area. You can't control which opportunity shows up, but you can control how much
area it has to land on.

## What luckbox does

Every morning it gives you a short list of moves:

```
STARTUPS
  Ask Ada Lovelace how she priced her API launch          ● Lovelace   post
  Go to the founders' breakfast (Thu Oct 8, nearby)
PEOPLE
  Follow up with Grace Hopper about the intro                          follow-up
TELLING
  Post the before/after of your onboarding redesign                    idea
LOCAL
  Try the Tuesday bouldering meetup (Oct 6, 10 min away)
```

Click a line to see why it fits you and the link. `●` means someone you know is involved.

It covers both sides of the rectangle:

- **Doing:** events, posts, programs and people in your areas, judged against what you're working on.
- **Telling:** post ideas drawn from your recent work and what people are discussing this week.
- **People:** news about people you know, follow-ups on messages you sent, and who could introduce you.

It never sends anything. You act; you mark what was useful; it learns from the marks.

## You choose what it watches

Each interest is a **radar**. Write a paragraph about the interest (what you're after, who's worth
meeting, what to skip) and `luckbox radar draft` finds sources for it and writes the radar. Edit it
like any JSON file.

| For | Sources |
|---|---|
| Events near you | Luma (any city), Partiful, any events page, a weekly web search |
| Anything with a feed | RSS: blogs, Substack, subreddits, YouTube channels, Google News searches, GitHub releases, job boards |
| Tech | Hacker News |
| Research | arXiv, OpenAlex (new work by authors you follow), researchseminars.org talks |
| People you know | weekly news about them, follow-ups on messages you sent |
| Your own work | post ideas from your recent commits |

Starting points in [examples/radars](examples/radars): a local hobby scene, a job search, AI products,
people, telling, and a weekly wildcard.

## How it works

1. **Sources** pull new items from whatever your radars watch (table above).
2. **Claude** reads each item against your private notes (who you are, what you want, who you know)
   and decides whether there's a move for you, and why. Most items fail.
3. **Your list** is a local page. Keys: `j`/`k` move, `space` details, `o` open, `g` keep, `d` done,
   `r` replied, `x` dismiss.
4. **Your marks** go back to Claude as examples. Marking *done* adds that person to your network.

## Setup

Needs Python 3.9+ (standard library only), [Claude Code](https://claude.com/claude-code) logged in, and
macOS or Linux.

```sh
git clone https://github.com/chaitbuilds/luckbox && cd luckbox
python3 -m luckbox init                                  # a few questions
# write your notes: ~/luckbox-profile/me.md, now.md, interests/*.md
python3 -m luckbox radar draft ~/luckbox-profile/interests/<interest>.md
python3 -m luckbox daily                                 # first list
python3 -m luckbox schedule                              # every morning, plus the page at 127.0.0.1:8765
```

Optional: add people you know from a Google Takeout or LinkedIn export. Full guide:
[docs/SETUP.md](docs/SETUP.md).

## Privacy

- Your data stays in `~/.luckbox` and your notes folder. This repo holds no personal data.
- Mail is read as headers only. An exclude list drops people before anything is stored.
- Anything in your notes under a heading containing **Private** shapes the judging but never appears
  in a suggestion or a search query.
- For a project too sensitive to describe at all, see [docs/PRIVATE-PROJECTS.md](docs/PRIVATE-PROJECTS.md).

## Cost

Judging runs on Sonnet; only items involving people you know go to Opus. On a Claude subscription
that's plan usage. With an API key, expect cents a day after the first run.

## Status

Early. Luma and Partiful are read through undocumented public endpoints and may break.

MIT licensed.
