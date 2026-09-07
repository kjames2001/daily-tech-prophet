# Hermes skill: daily-tech-prophet

This directory is the drop-in Hermes skill package.

## Install

```bash
# from the repo root
cp -r skill/ ~/.hermes/skills/daily-tech-prophet/
```

(or with the CLI: `hermes skill install ./skill` on versions that
support it). Verify with `skill_view(name='daily-tech-prophet')` or the
`/skill daily-tech-prophet` command.

The skill teaches a Hermes agent how to run, test, troubleshoot, and
deploy the pipeline; the actual scripts stay in this repo (the skill
points to them). Keep the `references/` files in sync with `docs/` —
they are copies of the same sources of truth.