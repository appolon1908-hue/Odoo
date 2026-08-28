# Contact-center contract evidence

`canonical-endpoints.json` is the complete public route inventory required by the mission. It distinguishes source implementation from runtime certification. `adapter-required` and `contract-only` are explicit blockers, not passing states.

Kong route policy, Keycloak audience and scope checks, mTLS identity, replay behavior, status codes, schemas, rate limits, and correlation evidence must be certified against isolated staging before any endpoint is marked production-ready.
