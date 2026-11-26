# Step 8: operating documentation

Added docs/NEO4J_BACKENDS.md and docs/IU_NEO4J.md, linked from README and the
existing database guide. They cover the default, switching, local activation
and parking, credential locations without values, direct IU Bolt/no-auth,
visibility and schema migration, backup compatibility, opt-in power ownership,
WireGuard setup, the three-command SSH policy and troubleshooting.

agent/.env.example lists every new IU variable, the optional script Python,
and relevant existing registry/source/credential configuration. The IU source
example carries its explicit backend tag. No real secret values are included.

Validation: 36 connection/resolver tests pass (step8-tests.xml), documentation
relative links exist, new environment examples are present, and whitespace and
staged secret scans pass. The Step 9 diagnostic script is documented ahead of
its implementation in the next commit.
