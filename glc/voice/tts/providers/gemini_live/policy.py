"""
Guardrails policy for for gemini live TTS provide.

Validation Policy:
1. Input Text size (MAX and MIN)
2. output size  (MAX)

"""

from glc.voice.tts.base import TTSError
from glc.voice.tts.providers.gemini_live.schemas import TTSPolicyConfig


class TTSPolicy:
    def __init__(self, policy_config: TTSPolicyConfig):
        self.policy_config = policy_config

    def validate_input(self, input_text: str) -> None:
        stext = input_text.strip()
        # validate input max length
        if len(stext) > self.policy_config.input_max_len:
            raise TTSError(
                f"input text exceeded maximum limitation of {self.policy_config.input_max_len}", status=400
            )

        # validate inout min length
        if len(stext) < self.policy_config.input_min_len:
            raise TTSError(
                f"Input text is empty or below minimum length allowed of {self.policy_config.input_min_len}",
                status=400,
            )

    def validate_output(self, audio_size: bytes) -> None:

        # validate audio max size
        if len(audio_size) > self.policy_config.output_max_size:
            raise TTSError(
                f"Output size exceeded allowed size {self.policy_config.output_max_size}", status=400
            )
