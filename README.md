# The Weekly Brief

A personal news page: about 30 of the week's most important stories, grouped by topic (aerospace and business first), sized by importance, with jargon you can tap for a definition.

```
pipeline/sources.json   whitelist of outlets, their approximate political lean and trust weight  (edit freely)
pipeline/glossary.json  term -> plain-English definition                                          (edit freely)
pipeline/template.html  the page design
pipeline/update.py      fetch -> rank -> summarise -> render   (standard library only)
data/news.json          this week's stories
site/index.html         the finished page (open it in any browser)
.github/workflows/daily.yml   runs the update every day and publishes to GitHub Pages
```

Run locally: `python3 pipeline/update.py all` (or `render` to rebuild the page from data/news.json).
