# NPC Voice Studio

Minimal local zero-shot voice cloning app using the already installed OmniVoice package.

## Requirements

- Existing Conda environment: `npc-voice`
- Installed OmniVoice package and model cache inside that environment
- CUDA-capable GPU recommended; CPU is used when CUDA is unavailable
- A local reference audio file and matching transcript

No package installation is required for this project.

## Files

- `src/omnivoice_service.py` loads OmniVoice once and exposes `OmniVoiceService.generate(...)`.
- `src/f5_service.py` remains available temporarily as a rollback path.
- `scripts/test_generation.py` runs one OmniVoice smoke test and saves `generated_audio/test_output.wav`.
- `app.py` provides a minimal local Gradio interface.
- `src/voice_profiles.py` stores reusable reference audio and matching transcripts.

## Run The UI

From the project root:

```powershell
C:\Users\Example\miniconda3\envs\npc-voice\python.exe app.py
```

Open the local URL printed by Gradio, then upload a reference clip and enter its
exact transcript before generating new dialogue.

## Run The Smoke Test

From the project root:

```powershell
C:\Users\Example\miniconda3\envs\npc-voice\python.exe scripts\test_generation.py
```

The smoke test uses F5-TTS's bundled example WAV only as a convenient local
audio fixture while the rollback package remains installed. Inference is performed
by `OmniVoiceService`. To use your own reference, edit `scripts/test_generation.py`:

```python
ref_audio_path = "path/to/your/reference.wav"
ref_text = "Exact transcript of the reference audio."
```

Keep the reference clip clean, short, and accurately transcribed for best results.
