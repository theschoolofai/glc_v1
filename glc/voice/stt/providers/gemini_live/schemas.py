"""Pydantic models and constants for the Gemini Live STT provider."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

DEFAULT_MODEL = "models/gemini-3.1-flash-live-preview"
WS_ENDPOINT = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
)
DEFAULT_RESPONSE_MODALITIES = ["AUDIO"]
DEFAULT_LANGUAGE = "en"
WAV_HEADER_BYTES = 44
PCM_MIME_TYPE = "audio/pcm;rate=16000"


class GeminiLiveTextPart(BaseModel):
    text: str


class GeminiLiveSystemInstruction(BaseModel):
    parts: list[GeminiLiveTextPart] = Field(default_factory=list)


class GeminiLiveGenerationConfig(BaseModel):
    responseModalities: list[str] = Field(default_factory=lambda: DEFAULT_RESPONSE_MODALITIES)


class GeminiLiveSetupPayload(BaseModel):
    model: str = DEFAULT_MODEL
    generationConfig: GeminiLiveGenerationConfig = Field(default_factory=GeminiLiveGenerationConfig)
    outputAudioTranscription: dict[str, Any] = Field(default_factory=dict)
    systemInstruction: GeminiLiveSystemInstruction = Field(default_factory=GeminiLiveSystemInstruction)


class GeminiLiveSetupFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    setup: GeminiLiveSetupPayload


class GeminiLiveAudioInput(BaseModel):
    mimeType: str
    data: str


class GeminiLiveRealtimeInput(BaseModel):
    audio: GeminiLiveAudioInput | None = None
    audioStreamEnd: bool | None = None


class GeminiLiveAudioFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    realtimeInput: GeminiLiveRealtimeInput


class GeminiLiveAudioStreamEndFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    realtimeInput: GeminiLiveRealtimeInput


class GeminiLiveOutputTranscription(BaseModel):
    text: str = ""


class GeminiLiveServerContent(BaseModel):
    outputTranscription: GeminiLiveOutputTranscription | None = None
    inputTranscription: GeminiLiveOutputTranscription | None = None
    turnComplete: bool = False
    modelTurn: dict[str, Any] | None = None


class GeminiLiveResponseMessage(BaseModel):
    serverContent: GeminiLiveServerContent | None = None
