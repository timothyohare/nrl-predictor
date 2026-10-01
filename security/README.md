# Security regression and fuzz tests

Added 2026-09-27. Bounded seeded inputs (20260927), no production requests. These tests assert desired security properties; failures are actionable findings, not tests to skip. Tests use real application functions/handlers with mocked storage. They do not prove deployed authorization or cryptographic entropy.

Run from this directory:

```sh
node ~/dev/newdev/code-build-harness/harness/gates/ci.mjs --force
```

The nested harness binds only the focused security tests. Run the root gate separately for whole-project validation. No application source or existing harness binding is changed by this addition.
