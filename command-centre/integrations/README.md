# Integrations and MCP

No MCP server or external connector is activated in this release. This folder reserves the adapter boundary for future read-only and mutating integrations. Any future tool call must carry a declared capability, input schema, execution timeout, audit event, and approval policy. Network-bound and mutating tools must remain disabled until an isolated worker and per-tool approval UX are implemented.
