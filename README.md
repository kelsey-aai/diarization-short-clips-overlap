# diarization-short-clips-overlap

Companion code for the AssemblyAI blog post **Why speaker diarization breaks on short clips and overlapping speech**.

`check_speaker_labels.py` transcribes a recording with speaker labels on AssemblyAI-STT-3.7, prints the speaker-labeled transcript, and then flags the spots where speaker attribution is least reliable:

- **Talk time per speaker.** It marks any speaker with less than 30 seconds of speech, the minimum the docs recommend for a stable label.
- **Short turns.** Utterances under one second, which are usually back-channels like "yeah" and "mm-hmm".
- **Timestamp overlaps.** Places where consecutive utterances from different speakers share time, usually cross-talk.
- **Low speaker confidence.** Words whose `speaker_confidence` falls below a threshold you choose.

It calls the REST API directly with `requests`, like the Python tab in the [Speaker Diarization docs](https://www.assemblyai.com/docs/pre-recorded-audio/label-speakers).
- Why not the Python SDK: as of `assemblyai` 1.10.11, the SDK's `SpeakerOptions` has no `include_speaker_confidence` field.
- Without that field you get no per-word confidence back.

## Quick start

```bash
git clone https://github.com/kelsey-aai/diarization-short-clips-overlap.git
cd diarization-short-clips-overlap
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ASSEMBLYAI_API_KEY="your-api-key"
```

Get a key from the [AssemblyAI dashboard](https://www.assemblyai.com/dashboard/signup).

## Run it

```bash
# A voice note or short clip, speaker count unknown
python check_speaker_labels.py voice-note.m4a

# A public URL, with a speaker range
python check_speaker_labels.py https://assembly.ai/wildfires.mp3 --min-speakers 2 --max-speakers 3

# You know the exact count
python check_speaker_labels.py support-call.wav --speakers 2

# Each participant recorded on their own channel
python check_speaker_labels.py stereo-call.wav --multichannel

# Flag more words for review
python check_speaker_labels.py meeting.mp3 --threshold 0.7
```

## Options

| Flag | What it does |
|---|---|
| `--speakers N` | Sets `min_speakers_expected` and `max_speakers_expected` to N. The API doesn't accept `speakers_expected` together with `speaker_options`, and confidence scores need `speaker_options`. |
| `--min-speakers`, `--max-speakers` | Hard lower and upper limits. If more people speak than the max, the extra voices are merged into existing labels. |
| `--multichannel` | Transcribes each channel separately. Labels come back as `1A`, `2A`, and so on. Speaker limits apply **per channel**. |
| `--threshold` | Speaker-confidence cutoff for flagging words. The default is 0.5. Tune it on your own audio. |
| `--max-rows` | Rows printed per section (default 15). |

## Notes

- `audio_duration` in the response is in seconds. Utterance and word `start`/`end` values are in milliseconds.
- `speech_model_used` tells you which model ran.
- The code was checked against the live docs and the OpenAPI spec. It has not been run against the live API.
