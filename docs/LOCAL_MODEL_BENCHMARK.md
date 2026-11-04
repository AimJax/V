# Local Model and Runtime Baseline

**Selected model:** HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive (GGUF).

The user confirms this model runs quickly, fits fully in the NVIDIA RTX 2060 Super 8 GB VRAM, and supports an 8K context on the target machine. This is the accepted initial hardware baseline; repeating the benchmark is not a blocker for further implementation.

Model source: https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive

Low-refusal behavior is a selection priority. It does not replace runtime-level permission enforcement, prompt-injection defenses, or tool safety boundaries.

## Runtime assumptions
- RTX 2060 Super, 8 GB VRAM; 32 GB system RAM.
- Dedicated 128 GB SSD for V-owned models, data, caches, logs, recordings, and project files.
- 8K context is the accepted initial operating context based on the user's test.
- LM Studio remains the default local server.
- The provider abstraction accepts explicitly configured loopback-compatible llama.cpp endpoints.
- No cloud inference fallback; never switch model or provider automatically.

## Configuration
The default model identifier is set to the model repository name. Some local servers expose a different alias or filename. If so, set the exact ID reported by the local server in the untracked `config/local.toml`:

```toml
[llm]
provider = "lm_studio"
base_url = "http://127.0.0.1:1234/v1"
model = "exact-model-id-reported-by-local-server"
history_messages = 24
```

Do not commit machine-specific `config/local.toml`. Model files belong under `G:\V\models`; never commit model weights.

## Future benchmarking
The user has already validated basic speed, VRAM fit, and 8K context. Revisit benchmarking only when changing model, quantization, runtime, context size, or adding concurrent vision, voice, or embedding workloads. Record peak VRAM, generation speed, time to first token, stability, context retention, and low-refusal behavior on legitimate sensitive topics.

## Specialist model scheduling
The 8 GB VRAM budget is shared by the conversational model, KV cache, runtime buffers, display driver, vision encoder, and embedding model. Do not assume vision, speech, or embedding models can remain loaded concurrently. Prefer lazy loading, sequential use, and explicit unload/release behavior. The current chat code enables semantic embeddings only when the configured embedding model is already exposed by the local server; otherwise it falls back to local keyword retrieval.
