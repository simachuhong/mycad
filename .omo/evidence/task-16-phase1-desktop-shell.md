# Todo 16 process evidence: T3 LoongArch64 spike -> no-go + ADR-006 update

Probes (timebox honored, no compile, no hardware, no CI change):
1. official PyPI full-history wheel scan via JSON API -> 0 loongarch files in ALL
   releases of cadquery-ocp-novtk / build123d / PySide6 / numpy.
2. pypi.loongnix.cn devpi stage discovery: /simple/<pkg> (302->404),
   /root/pypi/+simple/<pkg> (500), /loongson/pypi/+simple/<pkg> (200) — scan of
   the seven relevant package indexes; only legacy loong wheels exist
   (numpy<=1.8.2 cp36, PySide6 6.2.0 cp37/38) and none for the cadquery/OCP family.
3. Source-build OCCT/OCP assessment kept to literature-level (no compile).

ADR-006 edits: T3 bullet resolved no-go with resolution date + evidence pointer +
re-trigger criteria; baseline paragraph + T2 gain the PySide6 6.12.0
manylinux_2_39_aarch64 glibc gate finding from todo 15. Required ADR tokens
(glibc / 2.31 / LoongArch / manylinux_2_31) preserved; no blocklisted
phase-0 phrases introduced; FORBIDDEN_CI_TOKENS (ci.yml) untouched.

Verification: `pytest tests/test_adr_docs.py tests/test_scope_audit.py -q`.

Note: devpi stage path discovery was needed because naive /simple/<pkg> probes
404 — recorded so future re-evaluations skip the detour.
