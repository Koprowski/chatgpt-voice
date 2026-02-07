# Why Piggyback ChatGPT's Web Transcription

## The Three Options for Speech-to-Text

### Option A: Local Whisper (e.g., whisper.cpp, faster-whisper)

Run OpenAI's Whisper model locally on your machine.

**Costs:** Free (no API fees).

**Problems:**
- **Slow on modest hardware.** Whisper large-v3 (the model that produces ChatGPT-quality results) requires significant GPU VRAM or runs painfully slowly on CPU. On a laptop like a Dell Latitude E6430 with no dedicated GPU, expect 10-30+ seconds of processing for a few seconds of speech. The "tiny" and "base" models are faster but substantially less accurate — they miss punctuation, mangle uncommon words, and struggle with accents or background noise.
- **Quality-speed tradeoff.** You're forced to choose: fast but inaccurate (tiny/base models) or accurate but slow (large model). There is no "fast and accurate" option on consumer hardware without a modern NVIDIA GPU with 6+ GB VRAM.
- **Setup overhead.** Requires installing CUDA/cuDNN (for GPU acceleration), compiling whisper.cpp, or managing Python environments with PyTorch. Audio capture configuration (PulseAudio/PipeWire, sample rates, input devices) adds another layer of troubleshooting.
- **No streaming.** Most local Whisper implementations process the entire audio file after recording stops, adding a hard delay proportional to recording length. Real-time/streaming local Whisper exists but is experimental and even more resource-intensive.
- **Model updates are manual.** When OpenAI releases improved Whisper models, you need to download and configure them yourself.

### Option B: OpenAI Whisper API (paid)

Send recorded audio to OpenAI's cloud API endpoint.

**Costs:** $0.006 per minute of audio. Seems cheap, but:
- Requires an OpenAI API key and billing account
- Costs accumulate with heavy dictation use (dozens of transcriptions per day)
- You're paying for something ChatGPT gives you for free with a basic account

**Problems:**
- **Not free.** Even at $0.006/min, it's a recurring cost for something that has a free alternative.
- **API key management.** Need to securely store and rotate API keys. Risk of unexpected charges if the key is compromised.
- **Still requires local audio recording.** You still need to set up `arecord`, `parecord`, `sounddevice`, or similar to capture microphone audio, encode it properly (WAV/FLAC/MP3), and send it. This is the same audio plumbing hassle as local Whisper.
- **Network latency.** Round-trip to OpenAI's API adds 1-3 seconds depending on connection and audio length. Not terrible, but not instant either.
- **Rate limits.** API has rate limits that could matter for heavy use.

### Option C: ChatGPT Web Transcription Daemon (this approach)

Automate ChatGPT's web interface voice dictation via a background Playwright browser.

**Requirements:** You must have a **paid ChatGPT account** (e.g. ChatGPT Plus) and be signed in. Voice dictation is available to paid subscribers.

**Costs:** No additional fee beyond your ChatGPT subscription; voice dictation is included for paid accounts.

**Advantages over both alternatives:**

1. **Fast.** ChatGPT's web transcription uses their optimized server-side Whisper infrastructure. Transcription typically completes in 1-2 seconds regardless of your local hardware. No GPU required.

2. **No extra API cost.** No separate API key or per-minute audio charges. Voice dictation is included with a paid ChatGPT subscription. You use a feature you already have access to.

3. **Accurate.** Same Whisper large model running on OpenAI's optimized infrastructure. Proper punctuation, capitalization, handling of technical terms, numbers, and mixed-language content. No quality compromises from using a smaller model.

4. **Zero audio plumbing.** The browser handles all microphone access via the Web Audio API. No need to configure PulseAudio/PipeWire capture devices, audio formats, sample rates, or encoding. If your mic works in a browser, it works here.

5. **Always up to date.** When OpenAI improves their transcription model, you get the improvement automatically. No model downloads or updates.

6. **System-wide.** Works from any application — terminal, text editor, browser, email client. Single keyboard shortcut toggles recording on/off, text is pasted directly into wherever your cursor is.

7. **No Python ML stack.** No PyTorch, no CUDA, no cuDNN, no model files consuming gigabytes of disk. The only heavy dependency is Playwright (for browser automation).

8. **Cross-platform.** Works on Linux (Wayland and X11), Windows, and macOS with the same core logic. Platform-specific details (clipboard, paste injection, notifications, hotkeys) are handled by an abstraction layer.

## Tradeoffs of This Approach

This approach is not without downsides — they're worth understanding:

- **Fragile selectors.** ChatGPT's web UI changes periodically. When they update button labels or DOM structure, the CSS selectors in `config.json` need updating. This is the primary maintenance burden. Mitigated by using `aria-label` selectors (more stable than class names) and making them user-configurable.

- **Requires a ChatGPT account.** Free tier works, but you need an account and must log in once via the Playwright browser.

- **Background resource usage.** A minimized Chromium instance consumes ~400-500 MB of RAM. On a system with 8+ GB this is negligible; on a very constrained system it matters.

- **Internet required.** Transcription happens on OpenAI's servers. No offline capability. (This is also true of the paid API option, and effectively true of local Whisper on hardware too slow to run it usably.)

- **Privacy.** Your audio is sent to OpenAI's servers, same as using ChatGPT normally. If you need fully offline, air-gapped transcription, local Whisper is the only option (despite its speed issues).

- **Session expiry.** ChatGPT's login session eventually expires. When this happens, you need to re-run `python -m chatgpt_voice login` to re-authenticate. In practice this is infrequent (weeks/months).

## Summary

| | Local Whisper | Whisper API (paid) | ChatGPT Web (this) |
|---|---|---|---|
| **Cost** | Free | $0.006/min | Free |
| **Speed** | Slow (no GPU) / Fast (good GPU) | 1-3s | 1-2s |
| **Accuracy** | Depends on model size | High | High |
| **Punctuation** | Depends on model | Yes | Yes |
| **Setup complexity** | High (CUDA, models, audio) | Medium (API key, audio capture) | Medium (Playwright, one-time login) |
| **Hardware requirements** | GPU for usable speed | None | None |
| **Maintenance** | Model updates | API key rotation | Selector updates |
| **Offline capable** | Yes | No | No |
| **Audio config needed** | Yes | Yes | No (browser handles it) |
| **RAM overhead** | 1-6 GB (model) | Minimal | ~400-500 MB (Chromium) |
| **Cross-platform** | Yes | Yes | Yes |

For a desktop user who wants fast, accurate, free dictation without a powerful GPU, automating ChatGPT's web transcription is the practical sweet spot.
