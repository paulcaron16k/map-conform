# Security policy

## Reporting a vulnerability

Please report security problems privately, not in a public issue: on GitHub, open the
repository's **Security** tab and choose **Report a vulnerability**. Include the version, a
spec or input that shows the problem, and its impact. You will get an answer within a week,
and a fix or a plan with a timeline once the report is confirmed. Credit is given in the
release notes unless you prefer otherwise.

## Supported versions

Fixes go into the latest release. Before 1.0 there is one supported line: the newest
`0.x` version on PyPI.

## What is in scope

map-conform runs inside data pipelines, often with access to credentials and personal data.
These are vulnerabilities:

- **Escaping the expression sandbox.** Spec expressions (`expr`, `when`, `filter`, `case`)
  run in a restricted evaluator (`map_conform/expr/sandbox.py`): no imports, no attribute
  access outside an allowed list, no private names, bounded sizes. Any way for a spec to run
  arbitrary code, read files or the environment, or exhaust memory or time beyond those
  bounds through an expression is in scope.
- **Bypassing the UDF opt-in.** Python functions named by module path in a spec run only with
  `allow_python_udfs: true`. Any way for a spec to import or run Python without it is in
  scope.
- **Leaking secrets or personal data.** Salts, token keys or masked values appearing in
  logs, error messages, metrics or output where the spec masks them; a masking step that
  fails open.
- **Writing outside the configured locations** for BATCH output or rejects.

## What is not

- **UDFs and installed plugins** are trusted Python code by design: a UDF the spec enables,
  or a package that registers `map_conform.functions` entry points, can do anything Python
  can.
- **Whoever controls the spec** controls the pipeline's transformations; treat a spec like
  code and review it.
- The strength of `hash` without a salt, or of `mask`, against guessing: choose `tokenize`
  with a secret key, or a salted hash, for values that can be enumerated.
