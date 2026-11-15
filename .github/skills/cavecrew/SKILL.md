# cavecrew

Use compressed specialist delegation when it saves context:

- `cavecrew-investigator`: locate definitions, callers, and usages.
- `cavecrew-builder`: make a surgical edit in one or two known files.
- `cavecrew-reviewer`: review a diff and report findings.

Use the main thread for new features, three-or-more-file changes, and
cross-cutting refactors. Do not use a builder until the target file is known.
Do not delegate a task that is already clear and small.

Output contracts:

`cavecrew-investigator`

```text
<Header>:
- path:line — `symbol` — short note
totals: <counts>.
```

`cavecrew-builder`

```text
<path:line-range> — <change ≤10 words>.
verified: <re-read OK | mismatch @ path:line>.
```

`cavecrew-reviewer`

```text
path:line: <severity>: <problem>. <fix>.
totals: N high N medium N low N unknown
```

Reject unsupported absence claims. Verify cited lines and review results before
acting. Drop compressed voice for security warnings and irreversible actions.
