"""Transcribe a recording with speaker labels on AssemblyAI-STT-3.7 and flag
the places where speaker attribution is least reliable: speakers with little
airtime, very short turns, overlapping timestamps, and words with a low
speaker confidence score.

Usage:
    python check_speaker_labels.py voice-note.m4a
    python check_speaker_labels.py https://assembly.ai/wildfires.mp3 --min-speakers 2 --max-speakers 3
    python check_speaker_labels.py call.wav --speakers 2
    python check_speaker_labels.py stereo-call.wav --multichannel
"""

import argparse
import os
import sys
import time
from collections import defaultdict

import requests

BASE_URL = "https://api.assemblyai.com"

# The docs recommend at least 30 seconds of speech per speaker for a stable label.
MIN_SPEECH_PER_SPEAKER_MS = 30_000
# Turns shorter than this are usually back-channels ("yeah", "mm-hmm").
SHORT_TURN_MS = 1_000


def get_headers():
    api_key = os.environ.get("ASSEMBLYAI_API_KEY")
    if not api_key:
        sys.exit("Set the ASSEMBLYAI_API_KEY environment variable first.")
    return {"authorization": api_key}


def upload_if_local(audio, headers):
    if audio.startswith(("http://", "https://")):
        return audio
    with open(audio, "rb") as f:
        response = requests.post(f"{BASE_URL}/v2/upload", headers=headers, data=f)
    response.raise_for_status()
    return response.json()["upload_url"]


def build_request(audio_url, args):
    # speaker_options and speakers_expected can't be sent together, and
    # include_speaker_confidence lives inside speaker_options. To pin an exact
    # count and still get confidence scores, set min and max to the same value.
    speaker_options = {"include_speaker_confidence": True}
    if args.speakers:
        speaker_options["min_speakers_expected"] = args.speakers
        speaker_options["max_speakers_expected"] = args.speakers
    else:
        if args.min_speakers:
            speaker_options["min_speakers_expected"] = args.min_speakers
        if args.max_speakers:
            speaker_options["max_speakers_expected"] = args.max_speakers

    body = {
        "audio_url": audio_url,
        "speech_models": ["assemblyai-stt-3-7"],
        "speaker_labels": True,
        "speaker_options": speaker_options,
    }
    if args.multichannel:
        # Each channel is transcribed separately; labels come back as "1A", "2A".
        # speaker_options apply per channel.
        body["multichannel"] = True
    return body


def transcribe(body, headers):
    response = requests.post(f"{BASE_URL}/v2/transcript", headers=headers, json=body)
    response.raise_for_status()
    transcript_id = response.json()["id"]
    polling_url = f"{BASE_URL}/v2/transcript/{transcript_id}"

    while True:
        result = requests.get(polling_url, headers=headers).json()
        if result["status"] == "completed":
            return result
        if result["status"] == "error":
            raise RuntimeError(f"Transcription failed: {result['error']}")
        time.sleep(3)


def fmt_ms(ms):
    return f"{ms / 1000:7.2f}s"


def report(transcript, threshold, max_rows):
    utterances = transcript.get("utterances") or []
    duration_s = transcript.get("audio_duration") or 0  # seconds, not ms

    talk_ms = defaultdict(int)
    for u in utterances:
        talk_ms[u["speaker"]] += u["end"] - u["start"]

    print(f"Model used:     {transcript.get('speech_model_used')}")
    print(f"Audio duration: {duration_s}s")
    print(f"Speakers found: {len(talk_ms)}")
    print()

    print("Talk time per speaker")
    for speaker, ms in sorted(talk_ms.items()):
        flag = "  <- under 30s of speech, label may be unstable" if ms < MIN_SPEECH_PER_SPEAKER_MS else ""
        print(f"  {speaker:>4}: {fmt_ms(ms)}{flag}")
    print()

    short_turns = [u for u in utterances if u["end"] - u["start"] < SHORT_TURN_MS]
    print(f"Short turns (< {SHORT_TURN_MS} ms): {len(short_turns)}")
    for u in short_turns[:max_rows]:
        conf = u.get("speaker_confidence")
        conf_txt = f"  speaker_confidence={conf:.2f}" if conf is not None else ""
        print(f"  {fmt_ms(u['start'])}  {u['speaker']:>4}: {u['text']!r}{conf_txt}")
    print()

    # The transcript is serialized: one speaker per word. When two people talk
    # at once, consecutive utterances from different speakers can share time.
    overlaps = [
        (a, b)
        for a, b in zip(utterances, utterances[1:])
        if a["speaker"] != b["speaker"] and b["start"] < a["end"]
    ]
    print(f"Timestamp overlaps between consecutive speakers: {len(overlaps)}")
    for a, b in overlaps[:max_rows]:
        print(f"  {fmt_ms(b['start'])}  {a['speaker']} -> {b['speaker']}  ({a['end'] - b['start']} ms shared)")
    print()

    low_words = [
        w
        for u in utterances
        for w in u.get("words", [])
        if w.get("speaker_confidence") is not None and w["speaker_confidence"] < threshold
    ]
    print(f"Words with speaker_confidence < {threshold}: {len(low_words)}")
    for w in low_words[:max_rows]:
        print(f"  {fmt_ms(w['start'])}  {w['speaker']:>4}: {w['text']!r}  ({w['speaker_confidence']:.2f})")
    if not any("speaker_confidence" in w for u in utterances for w in u.get("words", [])):
        print("  (no speaker_confidence in the response; check speaker_options)")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("audio", help="Local file path or public URL")
    parser.add_argument("--speakers", type=int, help="Exact number of speakers, if you know it")
    parser.add_argument("--min-speakers", type=int, help="Hard lower limit on speaker labels")
    parser.add_argument("--max-speakers", type=int, help="Hard upper limit on speaker labels")
    parser.add_argument("--multichannel", action="store_true", help="Transcribe each channel separately")
    parser.add_argument("--threshold", type=float, default=0.5,
                        help="Flag words below this speaker confidence (default 0.5; tune on your audio)")
    parser.add_argument("--max-rows", type=int, default=15, help="Rows to print per section")
    args = parser.parse_args()

    if args.speakers and (args.min_speakers or args.max_speakers):
        parser.error("Use --speakers or --min-speakers/--max-speakers, not both.")

    headers = get_headers()
    audio_url = upload_if_local(args.audio, headers)
    transcript = transcribe(build_request(audio_url, args), headers)

    for u in transcript.get("utterances") or []:
        print(f"Speaker {u['speaker']}: {u['text']}")
    print("\n" + "-" * 60 + "\n")
    report(transcript, args.threshold, args.max_rows)


if __name__ == "__main__":
    main()
