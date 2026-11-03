# RATE V11 Intraday Activation Readiness V1

This package defines the **pure offline readiness boundary** between the already
merged Intraday admission validators and any future Production activation
implementation.

It does not select a provider, read credentials, run a live request, modify a
registry, modify a scheduler, publish Production state, resolve the external
dependency, or grant Production/CER-081 credit.

## Trust roots

A readiness package must be independently bound to:

- current main SHA;
- Control Center decision ID;
- accepted activation-permit SHA-256;
- accepted provider-authority binding SHA-256;
- accepted payload-qualification SHA-256.

The package cannot supply replacement values for those trust roots.

## Repository-rooted preimage

The validator computes SHA-256 directly from the current repository for the exact
existing files that a future activation implementation may need to change:

1. `config/RATE_EXTERNAL_PRODUCTION_DEPENDENCIES.json`
2. `config/SOURCE_REGISTRY.json`
3. `config/RATE_PRODUCTION_OFFICIAL_SOURCE_REGISTRY_V1.json`
4. `src/phase2_production.py`
5. `scripts/build_phase2_production_source.py`
6. `.github/workflows/rate_production_0930_scheduler.yml`
7. `.github/workflows/rate_production_1200_scheduler.yml`

A caller-provided preimage map must match those repository bytes exactly. Extra or
missing mutation paths fail closed.

## Pre-live boundary

A PASS means only **ENGINEERING_READINESS_ONLY**.

Before live provider qualification, the readiness package must keep:

- provider selected = false;
- provider name = null;
- endpoint = null;
- live qualification = REQUIRED_NOT_YET_BOUND;
- activation execution = NOT_AUTHORIZED;
- fallback = false;
- automatic retry = false;
- Production credit = 0;
- CER-081 credit = 0.

Downstream gates remain:

1. live provider qualification;
2. independent live review;
3. Control Center final activation decision;
4. separately reviewed activation implementation.
