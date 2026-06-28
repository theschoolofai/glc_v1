import asyncio
import base64
import time
from pathlib import Path

from glc.voice.tts.providers.kokoro.adapter import Provider

# Showcase sentences highlighting local execution, model caching, and zero latency.
SENTENCE_1 = (
    "Hello! This is the Kokoro text-to-speech engine running locally inside the GLC gateway. "
    "The first call lazy-loads the eighty-two million parameter model from local weights, which "
    "takes a couple of seconds to initialize."
)

SENTENCE_2 = (
    "This second sentence is synthesized almost instantaneously. Because the Kokoro pipeline "
    "is cached in memory as a module-global singleton, subsequent calls have zero reloading "
    "overhead and zero network latency. Local-first, fast, and completely free."
)

SENTENCE_3 = (
    "Indeed! We can also change the voice profiles easily. This third sentence is spoken "
    "by a male voice profile to demonstrate that the voice I D parameter is fully wired "
    "and functioning correctly."
)


async def main():
    # Instantiate the Kokoro provider without a mock to trigger the real execution path.
    provider = Provider(config={})

    print("=============================================================")
    # Step 1: First synthesis (model lazy loading)
    print("Step 1: Running first synthesis (this lazy-loads the model weights)...")
    start_time = time.perf_counter()
    result1 = await provider.synthesize(SENTENCE_1, voice_id="af_bella")
    end_time = time.perf_counter()
    duration1 = end_time - start_time

    # Save the output audio file
    output_path1 = Path("demo_step1_load.wav")
    wav_bytes1 = base64.b64decode(result1.audio_b64)
    output_path1.write_bytes(wav_bytes1)

    print(f"-> Saved: {output_path1.resolve()}")
    print(f"-> Time elapsed: {duration1:.3f} seconds")
    print(
        f"-> Sample Rate: {result1.sample_rate} Hz, Provider: {result1.provider}, Cost: ${result1.cost_usd:.2f}"
    )
    print("=============================================================")

    # Step 2: Second synthesis (caching and reuse validation)
    print("Step 2: Running second synthesis (demonstrating cached pipeline reuse)...")
    start_time = time.perf_counter()
    result2 = await provider.synthesize(SENTENCE_2, voice_id="af_bella")
    end_time = time.perf_counter()
    duration2 = end_time - start_time

    # Save the output audio file
    output_path2 = Path("demo_step2_reuse.wav")
    wav_bytes2 = base64.b64decode(result2.audio_b64)
    output_path2.write_bytes(wav_bytes2)

    print(f"-> Saved: {output_path2.resolve()}")
    print(f"-> Time elapsed: {duration2:.3f} seconds")
    print(f"-> Speedup: {duration1 / duration2:.1f}x faster!")
    print(
        f"-> Sample Rate: {result2.sample_rate} Hz, Provider: {result2.provider}, Cost: ${result2.cost_usd:.2f}"
    )
    print("=============================================================")

    # Step 3: Different voice synthesis (caching still active)
    print("Step 3: Running third synthesis (demonstrating custom voice_id='am_adam')...")
    start_time = time.perf_counter()
    result3 = await provider.synthesize(SENTENCE_3, voice_id="am_adam")
    end_time = time.perf_counter()
    duration3 = end_time - start_time

    output_path3 = Path("demo_step3_voice_adam.wav")
    wav_bytes3 = base64.b64decode(result3.audio_b64)
    output_path3.write_bytes(wav_bytes3)

    print(f"-> Saved: {output_path3.resolve()}")
    print(f"-> Time elapsed: {duration3:.3f} seconds")
    print(
        f"-> Sample Rate: {result3.sample_rate} Hz, Provider: {result3.provider}, Cost: ${result3.cost_usd:.2f}"
    )
    print("=============================================================")
    print("\nVerification complete! Play the saved .wav files to listen to the audio.")


if __name__ == "__main__":
    asyncio.run(main())
