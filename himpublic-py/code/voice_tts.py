#!/usr/bin/env python3
"""
Voice TTS - Generate realistic voice audio using ElevenLabs

Usage:
    python voice_tts.py              # Interactive menu
    python voice_tts.py --generate   # Generate all preset phrases
    python voice_tts.py --say "Hi!"  # Generate single phrase
    python voice_tts.py --medical-demo  # Smoke test: medical_calm_female one sentence
"""

import logging
import os
import sys
import subprocess
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Output directory for audio files
OUTPUT_DIR = Path(__file__).parent.parent / "assets" / "audio"

# ElevenLabs voice ID - "Adam" voice (fitting!) — used when no preset / no env override
VOICE_ID = "pNInz6obpgDQGcFmaJgB"

# Model options: eleven_turbo_v2_5 (fast), eleven_multilingual_v2 (best quality)
MODEL_ID = "eleven_turbo_v2_5"

# TTS presets: select via preset="medical_calm_female" or env ELEVENLABS_TTS_PRESET=medical_calm_female
TTS_PRESETS = {
    "medical_calm_female": {
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.82,
            "similarity_boost": 0.90,
            "style": 0.10,
            "speed": 0.95,
            "use_speaker_boost": True,
        },
    },
}

# Preset phrases for Adam
PHRASES = {
    # Greetings
    "greeting_1.mp3": "Hey there! I'm Adam!",
    "greeting_2.mp3": "What's up! Ready to have some fun?",
    "greeting_3.mp3": "Good to see you!",
    
    # Celebrate
    "celebrate_1.mp3": "GOOOAL!",
    "celebrate_2.mp3": "YES! What a play!",
    "celebrate_3.mp3": "That's what I'm talking about!",
    "celebrate_4.mp3": "Incredible!",
    
    # Disappointed
    "disappointed_1.mp3": "Aww, so close!",
    "disappointed_2.mp3": "Ohhh, unlucky!",
    "disappointed_3.mp3": "Next time!",
    
    # High-five
    "high_five_1.mp3": "Up top!",
    "high_five_2.mp3": "Nice one!",
    "high_five_3.mp3": "Yeah! Awesome!",
    
    # Football specific
    "football_1.mp3": "Go long!",
    "football_2.mp3": "Touchdown!",
    "football_3.mp3": "Nice catch!",
    
    # General
    "intro.mp3": "Hey, I'm Adam! Let's have some fun!",
    "goodbye.mp3": "See you next time!",
}


def get_elevenlabs_client():
    """Get ElevenLabs client, checking for API key."""
    try:
        from elevenlabs import ElevenLabs
    except ImportError:
        print("ERROR: elevenlabs not installed.")
        print("Run: pip install elevenlabs")
        sys.exit(1)
    
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("ERROR: ELEVENLABS_API_KEY environment variable not set.")
        print("")
        print("Get your API key from: https://elevenlabs.io/app/settings/api-keys")
        print("Then run: export ELEVENLABS_API_KEY='your-key-here'")
        sys.exit(1)
    
    return ElevenLabs(api_key=api_key)


def _get_voice_id_for_preset(preset: Optional[str]) -> str:
    """Resolve voice_id: preset-specific env, then ELEVENLABS_VOICE_ID, then default VOICE_ID."""
    if preset == "medical_calm_female":
        vid = os.environ.get("ELEVENLABS_VOICE_ID_MEDICAL_CALM_FEMALE")
        if vid:
            return vid.strip()
    vid = os.environ.get("ELEVENLABS_VOICE_ID")
    if vid:
        return vid.strip()
    return VOICE_ID


def generate_audio(
    text: str,
    filename: str,
    client=None,
    preset: Optional[str] = None,
) -> bool:
    """Generate audio file from text using ElevenLabs.
    preset: None = current default (VOICE_ID, MODEL_ID). 'medical_calm_female' = calm female medical preset.
    Default preset can be set via env ELEVENLABS_TTS_PRESET=medical_calm_female.
    """
    if client is None:
        client = get_elevenlabs_client()
    effective_preset = preset or os.environ.get("ELEVENLABS_TTS_PRESET") or None
    voice_id = _get_voice_id_for_preset(effective_preset)
    model_id = MODEL_ID
    voice_settings = None
    if effective_preset and effective_preset in TTS_PRESETS:
        p = TTS_PRESETS[effective_preset]
        model_id = p["model_id"]
        voice_settings = p.get("voice_settings")
    logger.info("TTS preset=%s voice_id=%s model_id=%s", effective_preset or "default", voice_id, model_id)
    print(f"Generating: {filename} -> '{text}'")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = OUTPUT_DIR / filename
    try:
        kwargs = {
            "voice_id": voice_id,
            "text": text,
            "model_id": model_id,
        }
        if voice_settings:
            kwargs["voice_settings"] = voice_settings
        audio = client.text_to_speech.convert(**kwargs)
        with open(filepath, "wb") as f:
            for chunk in audio:
                f.write(chunk)
        print(f"  Saved: {filepath}")
        return True
    except Exception as e:
        print(f"  ERROR: {e}")
        return False


def generate_all_phrases(preset: Optional[str] = None) -> None:
    """Generate all preset phrases. preset: None or 'medical_calm_female'; env ELEVENLABS_TTS_PRESET overrides."""
    print("=" * 50)
    print("GENERATING ALL PRESET PHRASES")
    print("=" * 50)
    print(f"Output directory: {OUTPUT_DIR}")
    effective = preset or os.environ.get("ELEVENLABS_TTS_PRESET") or "default"
    print(f"TTS preset: {effective}")
    print(f"Total phrases: {len(PHRASES)}")
    print("")
    client = get_elevenlabs_client()
    success = 0
    failed = 0
    for filename, text in PHRASES.items():
        if generate_audio(text, filename, client, preset=preset):
            success += 1
        else:
            failed += 1
    print("")
    print(f"Done! Generated {success}/{len(PHRASES)} files.")
    if failed > 0:
        print(f"Failed: {failed}")


def generate_single(
    text: str,
    filename: Optional[str] = None,
    preset: Optional[str] = None,
) -> str:
    """Generate a single phrase, return filepath. preset: None or 'medical_calm_female'; env ELEVENLABS_TTS_PRESET overrides."""
    if filename is None:
        import hashlib
        hash_str = hashlib.md5(text.encode()).hexdigest()[:8]
        filename = f"custom_{hash_str}.mp3"
    client = get_elevenlabs_client()
    if generate_audio(text, filename, client, preset=preset):
        return str(OUTPUT_DIR / filename)
    return ""


def play_audio(filepath: str) -> None:
    """Play audio file using system player."""
    if not os.path.exists(filepath):
        print(f"File not found: {filepath}")
        return
    
    print(f"Playing: {filepath}")
    
    # Try different players
    players = [
        ["aplay", filepath],           # Linux ALSA
        ["paplay", filepath],          # PulseAudio
        ["afplay", filepath],          # macOS
        ["mpv", "--no-video", filepath],  # Cross-platform
    ]
    
    for player in players:
        try:
            subprocess.run(player, check=True, capture_output=True)
            return
        except (subprocess.CalledProcessError, FileNotFoundError):
            continue
    
    print("No audio player found. Install aplay, paplay, or mpv.")


def list_generated_files() -> None:
    """List all generated audio files."""
    if not OUTPUT_DIR.exists():
        print("No audio files generated yet.")
        return
    
    files = list(OUTPUT_DIR.glob("*.mp3")) + list(OUTPUT_DIR.glob("*.wav"))
    if not files:
        print("No audio files found.")
        return
    
    print(f"\nGenerated audio files in {OUTPUT_DIR}:")
    for f in sorted(files):
        size_kb = f.stat().st_size / 1024
        print(f"  {f.name} ({size_kb:.1f} KB)")


def interactive_menu() -> None:
    """Interactive menu for voice generation."""
    print("=" * 50)
    print("ADAM VOICE GENERATOR (ElevenLabs)")
    print("=" * 50)
    
    while True:
        print("\nOptions:")
        print("  1. Generate all preset phrases")
        print("  2. Generate custom phrase")
        print("  3. Play an audio file")
        print("  4. List generated files")
        print("  Q. Quit")
        
        choice = input("\nEnter choice: ").strip().lower()
        
        if choice == "1":
            generate_all_phrases()
        
        elif choice == "2":
            text = input("Enter phrase: ").strip()
            if text:
                filepath = generate_single(text)
                if filepath:
                    play_choice = input("Play it? (y/n): ").strip().lower()
                    if play_choice == "y":
                        play_audio(filepath)
        
        elif choice == "3":
            list_generated_files()
            filename = input("Enter filename to play: ").strip()
            if filename:
                filepath = OUTPUT_DIR / filename
                play_audio(str(filepath))
        
        elif choice == "4":
            list_generated_files()
        
        elif choice == "q":
            print("Goodbye!")
            break
        
        else:
            print("Invalid choice.")


MEDICAL_DEMO_SENTENCE = (
    "I'm here to help. Stay still if you can. A responder is on the way."
)
MEDICAL_DEMO_FILENAME = "medical_calm_female_demo.mp3"


def run_medical_demo() -> str:
    """Smoke test: synthesize one medical sentence with medical_calm_female preset; save to OUTPUT_DIR. Returns filepath or ''."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    filepath = generate_single(MEDICAL_DEMO_SENTENCE, filename=MEDICAL_DEMO_FILENAME, preset="medical_calm_female")
    if filepath:
        print(f"Medical demo saved: {filepath}")
    return filepath


def main():
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Generate voice audio with ElevenLabs")
    parser.add_argument("--generate", action="store_true", help="Generate all preset phrases")
    parser.add_argument("--say", type=str, help="Generate a single phrase")
    parser.add_argument("--play", type=str, help="Play an audio file")
    parser.add_argument("--list", action="store_true", help="List generated files")
    parser.add_argument("--medical-demo", action="store_true", help="Smoke test: medical_calm_female one sentence to assets/audio")
    
    args = parser.parse_args()
    
    if args.medical_demo:
        run_medical_demo()
    elif args.generate:
        generate_all_phrases()
    elif args.say:
        filepath = generate_single(args.say)
        if filepath:
            play_audio(filepath)
    elif args.play:
        play_audio(args.play)
    elif args.list:
        list_generated_files()
    else:
        interactive_menu()


if __name__ == "__main__":
    main()
