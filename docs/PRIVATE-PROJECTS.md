# Projects too private to describe

Some work can't be written down for any tool: an unpublished idea, a research claim you're not ready to
share. luckbox can still scout for it if you give it a **field map** instead of the idea.

A field map describes the neighborhood around the work the way a librarian would: which fields it sits
among, which problems and systems, which people and venues, which search terms, and what to skip. It
never states the idea itself, so it's safe even if someone reads it.

Run this where your private notes already live (not in luckbox), read the result as a stranger would,
and save it to `~/.luckbox/context/<project>-field.md`:

```
You have access to my private notes on this project. Write a field map for a separate tool that scouts
for people, papers, talks and workshops relevant to it. That tool must never learn the idea itself.

Describe the research neighborhood the way a well-read librarian would describe it to someone hunting
for the right people and papers. It must be safe to show a stranger. Do not state, paraphrase, summarize
or hint at the core idea, its argument or its mechanism. Use only the vocabulary the existing fields use.

1. Fields: established fields and subfields, each core / adjacent / peripheral, one line each.
2. Problems and systems: concrete phenomena, systems and open questions it would bear on.
3. Existing frameworks: named theories it touches, marked aligned / in tension / unclear. Names only.
4. Near misses: work that looks relevant but isn't, and why.
5. People and groups: who does the most relevant work, with institution. Mark [VERIFY] where unsure.
6. Venues: journals, arXiv categories, conferences, workshops, seminar series.
7. Search terms: 30-60 phrases as they appear in titles and abstracts.
8. Strong opportunities: what makes something worth acting on.

Under two pages. Before finishing, reread it as a stranger and delete anything from which the idea
could be reconstructed.
```

Then point a radar at it with `"context": ["local:context/<project>-field.md", "profile:me.md"]`, and add
a **Private** section to `me.md` saying moves must never describe the project.
