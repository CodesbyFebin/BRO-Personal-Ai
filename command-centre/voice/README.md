# Voice

Voice is intentionally off. There is no microphone permission, wake-word listener, STT, or TTS implementation in this package. The blueprint's optional pipeline is openWakeWord -> local STT -> task router -> local TTS, with cancellation/barge-in support; it requires a separate platform adapter and on-device latency testing before it can be enabled.
