"""
LiveKit Voice Agent with Strands LLM Integration

This agent connects to:
- Strands server (localhost:8080) as the LLM via OpenAI-compatible API
- Deepgram for STT
- ElevenLabs for TTS

The Strands server handles tool calling (weather, time, etc.) and streams
fillers immediately when a tool call is detected.
"""

import asyncio
import logging
import os
import time
from datetime import datetime
from typing import Dict, Any, List

from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    AutoSubscribe,
    JobContext,
    JobProcess,
    WorkerOptions,
    cli,
    llm,
    metrics,
)
from livekit.agents.voice import AgentSession, Agent
from livekit.agents import tokenize
from livekit.plugins import deepgram, openai, elevenlabs, silero

load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voice-agent")

# ============================================
# METRICS TRACKING
# ============================================

class MetricsCollector:
    """Collects and aggregates metrics for a session."""
    
    def __init__(self, job_id: str, room_id: str):
        self.job_id = job_id
        self.room_id = room_id
        self.session_start = time.time()
        
        # LLM metrics
        self.total_llm_tokens = 0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.llm_ttft_list: List[float] = []
        
        # TTS metrics
        self.total_tts_characters = 0
        self.tts_ttfb_list: List[float] = []
        
        # STT metrics
        self.total_stt_duration = 0.0
        
        # EOU metrics
        self.eou_list: List[float] = []
        
        # Turn tracking
        self.turn_count = 0
        self.total_requests = 0
        
        # Transcript
        self.transcript: List[Dict[str, str]] = []
    
    def add_llm_metrics(self, metrics_event):
        """Process LLM metrics event."""
        if hasattr(metrics_event, 'completion_tokens'):
            self.total_output_tokens += metrics_event.completion_tokens or 0
        if hasattr(metrics_event, 'prompt_tokens'):
            self.total_input_tokens += metrics_event.prompt_tokens or 0
        if hasattr(metrics_event, 'ttft') and metrics_event.ttft:
            self.llm_ttft_list.append(metrics_event.ttft)
        
        self.total_llm_tokens = self.total_input_tokens + self.total_output_tokens
        self.total_requests += 1
        logger.info(f"[METRICS] LLM: +{metrics_event.completion_tokens or 0} output tokens, TTFT={metrics_event.ttft}s")
    
    def add_tts_metrics(self, metrics_event):
        """Process TTS metrics event."""
        if hasattr(metrics_event, 'characters_count'):
            self.total_tts_characters += metrics_event.characters_count or 0
        if hasattr(metrics_event, 'ttfb') and metrics_event.ttfb:
            self.tts_ttfb_list.append(metrics_event.ttfb)
        logger.info(f"[METRICS] TTS: +{metrics_event.characters_count or 0} chars, TTFB={metrics_event.ttfb}s")
    
    def add_stt_metrics(self, metrics_event):
        """Process STT metrics event."""
        if hasattr(metrics_event, 'audio_duration'):
            self.total_stt_duration += metrics_event.audio_duration or 0.0
        logger.info(f"[METRICS] STT: +{metrics_event.audio_duration}s audio")
    
    def add_eou_metrics(self, metrics_event):
        """Process End of Utterance metrics."""
        if hasattr(metrics_event, 'end_of_utterance_delay') and metrics_event.end_of_utterance_delay:
            self.eou_list.append(metrics_event.end_of_utterance_delay)
        logger.info(f"[METRICS] EOU: {metrics_event.end_of_utterance_delay}s")
    
    def add_transcript(self, role: str, text: str):
        """Add to transcript."""
        self.transcript.append({
            "role": role,
            "text": text,
            "timestamp": datetime.now().isoformat()
        })
        if role == "assistant":
            self.turn_count += 1
    
    def get_summary(self, shutdown_reason: str = "normal") -> Dict[str, Any]:
        """Generate final session summary."""
        session_duration = time.time() - self.session_start
        
        # Calculate averages
        avg_ttft = sum(self.llm_ttft_list) / len(self.llm_ttft_list) if self.llm_ttft_list else 0
        avg_ttfb = sum(self.tts_ttfb_list) / len(self.tts_ttfb_list) if self.tts_ttfb_list else 0
        avg_eou = sum(self.eou_list) / len(self.eou_list) if self.eou_list else 0
        
        # Calculate costs (approximate)
        # GPT-4o: $5/1M input, $15/1M output
        llm_cost = (self.total_input_tokens * 0.000005) + (self.total_output_tokens * 0.000015)
        # Deepgram: $0.0125/minute
        stt_cost = (self.total_stt_duration / 60) * 0.0125
        # ElevenLabs: ~$0.30/1K chars
        tts_cost = (self.total_tts_characters / 1000) * 0.30
        
        return {
            "job_id": self.job_id,
            "room_id": self.room_id,
            "total_llm_tokens": self.total_llm_tokens,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tts_characters": self.total_tts_characters,
            "total_stt_audio_duration": self.total_stt_duration,
            "avg_ttft": avg_ttft,
            "avg_ttfb": avg_ttfb,
            "avg_eou": avg_eou,
            "llm_cost": llm_cost,
            "stt_cost": stt_cost,
            "tts_cost": tts_cost,
            "total_cost": llm_cost + stt_cost + tts_cost,
            "total_requests": self.total_requests,
            "turn_count": self.turn_count,
            "session_duration": session_duration,
            "shutdown_reason": shutdown_reason,
            "transcript": "\n".join([f"{t['role']}: {t['text']}" for t in self.transcript])
        }


# ============================================
# AGENT SETUP
# ============================================

def prewarm(proc: JobProcess):
    """Preload models for faster startup."""
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    """Main agent entrypoint."""
    logger.info(f"[AGENT] Starting for room: {ctx.room.name}")
    
    # Initialize metrics collector
    metrics_collector = MetricsCollector(
        job_id=ctx.job.id,
        room_id=ctx.room.name
    )
    
    # Wait for participant
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    participant = await ctx.wait_for_participant()
    logger.info(f"[AGENT] Participant joined: {participant.identity}")
    tts_preset = (participant.attributes or {}).get("tts_preset", "balanced")
    logger.info(f"[TTS] Using preset: {tts_preset}")
    
    # Initialize components
    
    # STT - Deepgram
    stt = deepgram.STT(
        model="nova-3",
        language="en",
    )
    
    # LLM - Strands via OpenAI-compatible API
    # This connects to your local Strands server
    # The OpenAI client will append /chat/completions to the base_url
    strands_llm = openai.LLM(
        base_url="http://localhost:8080",  # Your Strands server
        api_key="not-needed",  # Strands doesn't require API key
        model="gpt-4o",  # Model name (Strands ignores this, uses its own model)
    )
    
    def build_tts(preset: str) -> elevenlabs.TTS:
        """
        Preset matrix for internal testing.
        Controlled via participant attribute `tts_preset` (set by the Playground).
        """
        presets = {
            # Safe default: good balance of latency and naturalness.
            "balanced": dict(
                model="eleven_flash_v2_5",
                streaming_latency=3,
                chunk_length_schedule=[80, 120],
                min_sentence_len=5,
                stream_context_len=5,
            ),
            # Prioritize making filler clearly separate from tool result.
            "fast_sep": dict(
                model="eleven_flash_v2_5",
                streaming_latency=4,
                chunk_length_schedule=[50],
                min_sentence_len=1,
                stream_context_len=1,
            ),
            # Minimize buffering (lowest latency, may sound less natural).
            "ultra_low_latency": dict(
                model="eleven_flash_v2_5",
                streaming_latency=0,
                chunk_length_schedule=[50],
                min_sentence_len=1,
                stream_context_len=1,
            ),
            # More natural pacing, more buffering.
            "natural": dict(
                model="eleven_flash_v2_5",
                streaming_latency=3,
                chunk_length_schedule=[120, 200, 260],
                min_sentence_len=10,
                stream_context_len=10,
            ),
        }

        cfg = presets.get(preset, presets["balanced"])
        tokenizer = tokenize.blingfire.SentenceTokenizer(
            min_sentence_len=cfg["min_sentence_len"],
            stream_context_len=cfg["stream_context_len"],
        )

        return elevenlabs.TTS(
            model=cfg["model"],
            voice_settings=elevenlabs.VoiceSettings(
                stability=0.5,
                similarity_boost=0.75,
            ),
            auto_mode=True,
            word_tokenizer=tokenizer,
            chunk_length_schedule=cfg["chunk_length_schedule"],
            streaming_latency=cfg["streaming_latency"],
        )

    tts = build_tts(tts_preset)
    
    # VAD - Silero
    vad = ctx.proc.userdata.get("vad") or silero.VAD.load()
    
    # Create the agent
    agent = Agent(
        instructions="""You are a friendly and helpful AI assistant. You have access to tools for:
- Getting weather information for any city
- Getting the current time
- Doing calculations
- Setting reminders

Be conversational and natural. When you use a tool, the filler response and result will be 
streamed automatically - just respond naturally to the result.

Keep your responses concise and friendly. Don't repeat information that was just spoken.""",
    )
    
    # Create the session
    session = AgentSession(
        stt=stt,
        llm=strands_llm,
        tts=tts,
        vad=vad,
        # Voice activity detection settings
        min_endpointing_delay=0.5,
        max_endpointing_delay=1.0,
    )
    
    # ============================================
    # METRICS CALLBACKS (simplified for stability)
    # ============================================
    
    @session.on("metrics_collected")
    def on_metrics(event):
        """Handle metrics events - just log them."""
        try:
            # Log basic metrics without accessing specific attributes
            logger.debug(f"[METRICS] Collected: {type(event).__name__}")
        except Exception as e:
            logger.debug(f"[METRICS] Error: {e}")
    
    @session.on("user_input_transcribed")
    def on_user_input(event):
        """Log user speech."""
        if hasattr(event, 'transcript') and event.transcript:
            metrics_collector.add_transcript("user", event.transcript)
            logger.info(f"[USER] {event.transcript}")
    
    @session.on("agent_state_changed")
    def on_agent_state(event):
        """Track agent state changes."""
        # livekit.agents.voice.events.AgentStateChangedEvent uses old_state/new_state
        try:
            logger.info(f"[STATE] Agent state: {event.old_state} -> {event.new_state}")
        except Exception:
            logger.info(f"[STATE] Agent state changed: {event}")
    
    # ============================================
    # START SESSION
    # ============================================
    
    logger.info("[AGENT] Starting voice session...")
    await session.start(agent, room=ctx.room)
    
    # Greet the user
    await session.say(
        "Hey! I'm your AI assistant. I can tell you the real-time weather for any city worldwide. "
        "Try asking me about the weather in Delhi, Tokyo, or anywhere!"
    )
    
    # ============================================
    # SHUTDOWN CALLBACK
    # ============================================
    
    async def shutdown():
        """Handle graceful shutdown."""
        logger.info("[AGENT] Shutting down...")
        
        # Get final summary
        summary = metrics_collector.get_summary(shutdown_reason="participant_left")
        
        # Log summary
        logger.info("=" * 50)
        logger.info("[SESSION SUMMARY]")
        logger.info(f"  Duration: {summary['session_duration']:.1f}s")
        logger.info(f"  Turns: {summary['turn_count']}")
        logger.info(f"  LLM Tokens: {summary['total_llm_tokens']} (in: {summary['total_input_tokens']}, out: {summary['total_output_tokens']})")
        logger.info(f"  TTS Characters: {summary['total_tts_characters']}")
        logger.info(f"  STT Duration: {summary['total_stt_audio_duration']:.1f}s")
        logger.info(f"  Avg TTFT: {summary['avg_ttft']:.3f}s")
        logger.info(f"  Avg TTFB: {summary['avg_ttfb']:.3f}s")
        logger.info(f"  Avg EOU: {summary['avg_eou']:.3f}s")
        logger.info(f"  Estimated Cost: ${summary['total_cost']:.4f}")
        logger.info("=" * 50)
        
        # TODO: Save to Supabase here
        # await save_to_supabase(summary)
    
    # Wait for disconnect
    disconnect_event = asyncio.Event()

    @ctx.room.on("participant_disconnected")
    def on_participant_left(participant: rtc.RemoteParticipant):
        logger.info(f"[AGENT] Participant left: {participant.identity}")
        asyncio.create_task(shutdown())
        disconnect_event.set()

    @ctx.room.on("disconnected")
    def on_room_disconnected(reason):
        logger.info(f"[AGENT] Room disconnected: {reason}")
        disconnect_event.set()
    
    # Keep agent running (AgentSession doesn't expose `wait()` in this SDK version)
    await disconnect_event.wait()


# ============================================
# MAIN
# ============================================

if __name__ == "__main__":
    cli.run_app(
        WorkerOptions(
            entrypoint_fnc=entrypoint,
            prewarm_fnc=prewarm,
        ),
    )
