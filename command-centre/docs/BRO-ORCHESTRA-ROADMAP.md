# BRO command centre: implementation roadmap

## Current build: what is real today

BRO is a local Python HTTP service with a single-file HTML HUD and SQLite task history. The command panel submits to the local workflow; it does not run arbitrary tools.

| Area | Current implementation | Boundary |
| --- | --- | --- |
| Voice interaction | Opt-in browser push-to-talk, interim transcript, task feedback, browser text-to-speech, mic-to-interrupt, mute toggle | Browser speech support varies; recognition may use a browser speech service. No wake phrase, background mic, offline STT/TTS, or measured latency SLA |
| Routing | Transparent typed rule router with score and risk | Jev/Kev model is not installed; no learned routing or calibrated confidence |
| Agent workflow | Coordinator, worker, skeptic/verifier stages | One local workflow process; model roles are prompts, not independently scheduled agents |
| Review | Optional configured reviewer endpoints and structured agreement report | Agreement is not truth. Reviewer consensus cannot authorize actions |
| Memory | SQLite task episodes, events, and notes | Working state is in-process; semantic/vector and temporal graph layers are not configured |
| Human gate | Approval proposals and locally recorded approve/deny decision | Decisions are recorded only; the app performs no external action |
| HUD | Responsive cyberpunk command centre, mission board, event stream, safety cards, model configuration panel | Trading, DevOps, publishing, calendar, messaging and GitHub feeds are placeholders until connectors are configured |
| Security | Local bind default, explicit remote model trust labels, no action runner | No MCP, native OS sandbox, authentication, remote sync, or production security review |

## Target architecture

### 1. Shared command surface

Keep the browser HUD responsive, then add platform shells behind the same authenticated API: desktop first (Windows, macOS, Linux), then mobile clients. A platform client should own device capabilities such as notifications, microphone permissions, and secure credential storage. The server remains local-first; cross-device sync is an explicit opt-in with encryption and device revocation.

### 2. Queen coordinator and durable jobs

Every request becomes a durable job with an ID, owner, policy context, deadline, budget, idempotency key, and event history. The Queen plans small jobs, assigns bounded workers, and resumes interrupted work from job state rather than chat context. Each worker receives only its task inputs and declared tools. Retries are bounded, recorded, and safe to repeat. Human approval pauses the job; approval changes job state but does not silently bypass the tool's own capability checks.

### 3. Provider-aware model router

Treat models as providers behind adapters, not as a list of assumed interchangeable credentials. Route by task class, privacy boundary, observed availability, latency, cost ceiling, context size, and policy. Maintain separate adapters for official API endpoints, local inference servers, and authorized coding-agent runtimes. A user's product subscription is not assumed to be a generic API key; connect a CLI/app-server only through its supported authentication path. Keep a primary and fallbacks, test health before routing, and label data egress before a remote call. Maintain a registry of model capabilities and refresh it from provider configuration rather than hard-coding “all models.”

Use a second or third model only for independent review when the task justifies the extra latency and data exposure. Ask reviewers for claims, evidence, uncertainty, and counterarguments. Detect disagreement and missing evidence; never translate agreement into correctness or automatic authorization. For financial, security, production, or irreversible actions, stop at a human review card.

### 4. Layered temporal memory

Begin with SQLite as the durable source of truth. Add working/session state, episodic job records, semantic facts with provenance, and time-bounded entity/event relations as separate adapters. Every remembered item should carry source, timestamp, confidence, retention class, and user visibility. Provide inspect, correct, export, and delete operations. Do not treat generated summaries as verified facts.

### 5. Interruptible voice

Keep the present click-to-talk experience as the first interface. Next, use a local streaming STT/TTS adapter with partial transcripts, cancellation tokens, turn detection, and immediate barge-in. Add an optional wake-word service only after a clear device-level permission and visible listening indicator exist. Measure microphone-to-first-response, stop latency, and transcription error on target hardware; set a sub-two-second target only after a benchmark and identify whether it means first audio, final answer, or a command acknowledgement. Cloud speech is an explicit provider choice with an egress label.

### 6. Zero-trust tools and domain adapters

Expose tools through a capability registry: read-only status, bounded writes, destructive writes, financial orders, and credential operations are different capabilities. Each adapter gets scoped credentials, argument schemas, timeouts, output limits, an audit event, and an OS-level sandbox. MCP servers start disabled and are enabled one at a time with tool-level allowlists. The approval UI displays the exact arguments and consequences. Begin with read-only connectors; keep trading in simulation/paper mode by default and require explicit per-order confirmation before any live account path.

## Phased delivery and acceptance gates

1. **Voice and interface (now):** finish accessible push-to-talk and speech controls; test browser support/fallback, duplicate transcript suppression, cancellation, task errors, and FIFO spoken replies. Keep the privacy disclosure visible. No wake-word claim.
2. **Runtime foundation:** move jobs to a durable queue and define versioned provider/worker contracts. Test restart recovery, bounded retries, timeouts, idempotency, and remote-provider egress labels.
3. **Memory and routing:** add provenance-aware memory APIs and evaluate router decisions on a fixed task suite. Report latency, cost, abstentions, and incorrect routing; do not present heuristic confidence as model certainty.
4. **Tool sandbox:** implement one read-only adapter and one reversible write adapter in a disposable worker. Verify deny-by-default permissions, explicit arguments, audit logs, and timeout/kill behavior before adding integrations.
5. **Cross-platform clients:** package desktop and mobile clients against the same API; test local data location, credential isolation, mic/notification permissions, upgrade and recovery behavior per OS.
6. **Domain pilots:** start with DevOps read-only status and content draft/review. Add trading market data and paper simulation only after data provenance, account isolation, and risk limits pass review. Live order execution is a separately gated project.

## Routine catalog for future skills

The following are skill candidates, not implemented automations: morning calendar and priority digest; inbox triage; task due-date scan; meeting preparation; meeting notes and action extraction; daily project standup; open pull-request summary; CI failure triage; dependency/security advisory scan; service health summary; incident timeline draft; deployment checklist; release-note draft; repository change digest; content topic and draft queue; comment/reply draft review; scheduled-post preview; personal knowledge capture; weekly goals review; expense/subscription reminder; and paper-trading risk recap. Anything that sends, publishes, deploys, trades, deletes, or contacts another person must stop for user review.

## Supplied repository landscape: fit and caveats

This is a selection from the supplied list, based on README/metadata-level triage. Verify current code, licenses, dependency health, and threat model before borrowing code. Prefer interfaces and patterns; do not copy implementation blindly.

| Repository | Potential use in BRO | What to verify / decision |
| --- | --- | --- |
| [aden-hive/hive](https://github.com/aden-hive/hive) | Queen/worker planning, shared task tracker, resumable colonies | Strong orchestration reference. Preserve job-level isolation and inspect persistence/retry behavior before adoption |
| [swarmclawai/swarmclaw](https://github.com/swarmclawai/swarmclaw) | Self-hosted runtime, provider/tool abstractions, schedules | Candidate runtime comparison; validate permissions and actual provider capabilities |
| [HKUDS/DeepCode](https://github.com/HKUDS/DeepCode) | Shared session/runtime concepts across interfaces | Study session ownership, history, and tool permission boundaries |
| [eadmin2/jarvis_ai](https://github.com/eadmin2/jarvis_ai) | Voice HUD, transcripts, stop controls, review cards | Useful interaction reference. README describes cloud voice and multi-second response; not evidence of local sub-two-second voice |
| [artbyjazi/jarvis](https://github.com/artbyjazi/jarvis) | Offline conversational voice assistant | Inspect supported platforms, STT/TTS models, resource needs, and license before using as a voice backend |
| [browser-use/jev-ultrafast](https://github.com/browser-use/jev-ultrafast) | Typed constrained decisions for browser actions | Optional browser-only policy helper; never grant it broad computer or shell access |
| [NandhaKishorM/laya](https://github.com/NandhaKishorM/laya) | Fast typed routing/decision model | Benchmark against BRO tasks and compare abstention/calibration; not a replacement for authorization policy |
| [jaredpalmer/kev](https://github.com/jaredpalmer/kev) | Local decision-model research | Evaluate reproducibility and model compatibility; keep policy checks deterministic and separate |
| [reticlehq/reticle](https://github.com/reticlehq/reticle) | Outcome verification with pass/fail/uncertain states | Good verification concept; define observable outcomes and avoid treating an LLM verifier as a security boundary |
| [wshobson/agents](https://github.com/wshobson/agents) | Reusable role and skill definitions | Catalog/reference rather than durable runtime; review each skill's tool access and license |
| [grll/mcpadapt](https://github.com/grll/mcpadapt) | Adapter patterns for frameworks and MCP | Consider as an integration bridge only after tool-level allowlisting exists |
| [YaoApp/yao](https://github.com/YaoApp/yao) | Self-hosted workspace and multi-device task surface | Compare device ownership and sync design; do not merge identity/data models without a prototype |
| [OpenByteInc/QuantDinger](https://github.com/OpenByteInc/QuantDinger) | Trading research/backtest workflow reference | Isolate from BRO execution; evaluate paper-trading defaults, exchange credentials, and risk controls |
| [jonwiggins/optio](https://github.com/jonwiggins/optio) | Orchestration interface reference | Keep sample/fictional data visibly labeled in BRO demos |
| [phillwarren/jarvis-hud](https://github.com/phillwarren/jarvis-hud), [SuryaHarikrishnan/desktop-hud-kit](https://github.com/SuryaHarikrishnan/desktop-hud-kit), [28labsnz/omarchy-jarvis-theme](https://github.com/28labsnz/omarchy-jarvis-theme) | HUD layout and visual language | UI references, not proof of a working agent runtime |
| [multica-ai/multica](https://github.com/multica-ai/multica), [desplega-ai/agent-swarm](https://github.com/desplega-ai/agent-swarm), [affaan-m/claude-swarm](https://github.com/affaan-m/claude-swarm) | Additional orchestration comparisons | Compare durability, provider coupling, replayability, and human review before choosing a runtime |
| [FareedKhan-dev/kimi-k3-in-c](https://github.com/FareedKhan-dev/kimi-k3-in-c) | Experimental inference/runtime research | Not a practical default for this assistant; validate model footprint and hardware claims independently |

Other supplied projects appear to be individual desktop assistants, themes, quota/status HUDs, mobile clients, cybersecurity swarms, or domain-specific agent demos. They can inform a focused prototype, but they are not interchangeable parts of one safe production platform. The list includes potentially offensive security tooling; BRO should not import those capabilities into its general-purpose tool set.

## Provider and account integration note

Provider integrations must distinguish product subscriptions from API credentials. Kilo's documented `free` routes are a changing provider-routed selection of hosted free models, not a promise that every model remains available. OpenAI documents an app-server flow that can use a ChatGPT sign-in for Codex in supported contexts; that does not make the subscription a generic API key. Anthropic documents separate Claude Code authentication paths, including account and API options. BRO should implement an official adapter for each authorized runtime and show account, quota, billing, and data-routing boundaries separately.

Sources: [Kilo model selection](https://kilocode.ai/docs/customize/model-selection), [Kilo providers](https://kilocode.ai/docs/providers), [OpenAI Codex app-server](https://developers.openai.com/codex/app-server/), [Anthropic Claude Code setup](https://docs.anthropic.com/en/docs/claude-code/setup).

## Evidence and limitations

The current prototype was functionally tested with the repository's Python tests and static HTML/JavaScript checks. Browser-native microphone and speech output require an interactive browser with permission and are not exercised by those tests. No performance, privacy, model-quality, safety, or production deployment guarantee is made. Model debate and human review can reduce some errors; they cannot guarantee that responses are correct or hallucination-free.
