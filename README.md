# NPC Voice Studio

Minimal local zero-shot voice cloning wrapper using the already installed F5-TTS package.

## Requirements

- Existing Conda environment: `npc-voice`
- Installed F5-TTS package inside that environment
- A local reference audio file and matching transcript

No package installation is required for this project.

## Files

- `src/f5_service.py` loads F5-TTS once and exposes `F5VoiceService.generate(...)`.
- `scripts/test_generation.py` runs one local smoke test and saves `generated_audio/test_output.wav`.
- `app.py` provides a minimal local Gradio interface.

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

The script uses F5-TTS's bundled local example reference audio. To use your own voice reference, edit `scripts/test_generation.py`:

```python
ref_audio_path = "path/to/your/reference.wav"
ref_text = "Exact transcript of the reference audio."
```

Keep the reference clip clean, short, and accurately transcribed for best results.
