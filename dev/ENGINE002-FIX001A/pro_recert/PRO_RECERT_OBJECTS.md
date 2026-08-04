# ENGINE002-FIX001A Pro RECERT objects

Frozen history to verify:

| object | commit |
|---|---|
| ENGINE001 | `93e8bf79ff6fb6b6419d794b7ef70bac702b8665` |
| ENGINE002 original | `8c0d494f57f4594ff5acfd8e02ef546fcc387f0b` |
| ENGINE002-FIX001 | `94b45820b811e95ce29c9a9c062cbf8e8bbfbbdf` |
| ENGINE002-FIX001A | ordinary final evidence commit containing this file |

Because a Git commit cannot contain its own object ID, the exact FIX001A head
and tree are frozen in the external handoff manifest and SHA-256 sidecars made
after the evidence commit.  The complete Git bundle must reproduce that head
and the complete ancestry above.

The certified release is outside the development review object and remains:

```text
tag: v0.1.0
peeled commit: 17a0927095c7a067817bf598a2556cbe7348a6d0
```

The external Pro package indexes the original ENGINE002 handoff, FIX001
handoff, this FIX001A handoff, the frozen Pro preflight review, all external
sidecars, CI artifacts, prior large-offset evidence, authority/runtime/RSS
evidence, and the source bundle.  Inclusion is evidence organization, not a
Codex verdict on behalf of Pro.
