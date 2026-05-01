# Third-Party Notices

This file lists external code copied into iguanatrader's source tree under the original author's license, plus the attribution required by that license.

iguanatrader prefers to consume external code via standard package managers (Poetry / pnpm) rather than vendoring. Vendored code is the exception — and only when (a) the upstream license requires it, (b) the upstream is abandoned and we need to fork-with-attribution, or (c) we adapt a small snippet (≤30 lines) that's faster to inline than to depend on.

## No third-party code copied yet

As of 2026-04-30, no third-party source code has been copied into this repo. Slice 1 (`bootstrap-monorepo`) is dev-tooling only.

## Format for future entries

When code is copied into the repo, add an entry here using this template:

```
## <library / file> (<source URL>)

- **Path in repo**: `<path/to/copied/file>`
- **Original license**: <SPDX identifier>
- **Original copyright**: © <year> <author>
- **Modifications**: <none | brief description>
- **Why copied**: <rationale per the criteria above>
```
