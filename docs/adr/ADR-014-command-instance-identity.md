# ADR-014 — Persistent command instance identity

Status: Accepted for E2-A on 2026-11-02 by user implementation authorization; implemented with scoped validation. See [acceptance evidence](../../.omo/evidence/e2a-command-identity/acceptance.md).

## Decision

Archive v5 extends v4 by requiring a canonical hex UUID `instance_id` on every command record. The existing six audit fields and amendments keep their meaning. V1–v4 readers, validators and serialization retain their original field contracts; they reject the new field. No runtime FeatureId/TopologyId is persisted or reused as a command identity.

An explicit Bus upgrade allocates identity for active and redo commands using a signed, document/revision-bound proposal. Preparing or abandoning a proposal has no model effects. Applying it adopts the exact proposed identities transactionally and advances document revision. Failures restore history, redo, format, dirty and geometry. Upgrade remains v5 after undo. New v5 execution allocates new command identities; amendment, rebuild and redo preserve them.

V5 may adopt exact v4/v5 source snapshots; v4 cannot adopt v5 sources. Source fingerprints cover the original complete snapshot. No implicit source migration occurs during replay. Save As creates a new file identity while retaining document-local command identities and v5; callers cannot treat identical command UUIDs in different files as the same object.

Handlers receive a backend-neutral execution context. Built-in handlers use an optional contextual kernel capability; existing legacy kernel/plugin interfaces remain supported. A legacy plugin calling apply directly does not thereby acquire semantic lineage. Internal operation logs preserve contextual records across regeneration. Identity alone does not promise bindable faces.

## Consequences and boundaries

The per-command field follows existing command copies, amendments and undo stacks, avoiding a second parallel identity list. V5 consumers are required to read v5 files. Upgrading does not rewrite timestamps, confirmations or amendments and does not provide an immutable lifetime audit log. This decision adds no bound hole command, topology naming system or GUI repair flow. Binding consumers and positional intent belong to E2-B/E3.
