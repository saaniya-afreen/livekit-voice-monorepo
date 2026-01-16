# LiveKit Voice Agent

A production-ready voice AI agent built with LiveKit, featuring tool calling, real-time metrics, and Supabase integration.

## Features

- 🎤 **Voice Pipeline**: Deepgram STT → OpenAI LLM → ElevenLabs TTS
- 🛠️ **Tool Calling**: Weather (Open-Meteo API), time, calculator, reminders
- 📊 **Metrics Collection**: LLM tokens, TTS characters, STT duration, latency tracking
- 💾 **Supabase Integration**: Stores metrics, session summaries, and API call logs
- 🎙️ **Filler Responses**: Natural pauses during API calls to avoid silence
- 📝 **Transcript Logging**: Full conversation history saved per session
- 💰 **Cost Tracking**: Calculates LLM, STT, and TTS costs per session

## Setup

### 1. Clone the repository
```bash
git clone https://github.com/saaniya-afreen/livekit-voice-agent.git
cd livekit-voice-agent
```

### 2. Create virtual environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment
```bash
cp .env.example .env
# Edit .env with your API keys
```

### 5. Setup Supabase tables
Run this SQL in your Supabase SQL Editor:

```sql
CREATE TABLE session_summaries (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    job_id TEXT,
    room_id TEXT,
    total_llm_tokens INTEGER,
    total_input_tokens INTEGER,
    total_output_tokens INTEGER,
    total_tts_characters INTEGER,
    total_stt_audio_duration REAL,
    avg_ttft REAL,
    avg_ttfb REAL,
    avg_eou REAL,
    llm_cost REAL,
    stt_cost REAL,
    tts_cost REAL,
    total_cost REAL,
    total_requests INTEGER,
    turn_count INTEGER,
    session_duration REAL,
    shutdown_reason TEXT,
    transcript TEXT
);

CREATE TABLE metrics_events (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    job_id TEXT,
    room_id TEXT,
    metric_type TEXT,
    tokens INTEGER,
    ttft REAL,
    duration REAL,
    tokens_per_second REAL,
    characters INTEGER,
    ttfb REAL,
    audio_duration REAL,
    streamed BOOLEAN,
    idle_time REAL,
    inference_count INTEGER
);

CREATE TABLE api_calls (
    id BIGSERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    api_name TEXT,
    endpoint TEXT,
    city TEXT,
    response_summary TEXT
);
```

### 6. Run the agent
```bash
python agent.py start
```

## Usage

Connect to your LiveKit room using the [LiveKit Playground](https://github.com/livekit/agents-playground) or any LiveKit client.

## Playground UI (included in this repo)

This repo includes a local Playground UI under `playground/`.

Run it:

```bash
cd playground
pnpm install
pnpm dev
```

## LiveKit patch (FlushSentinel / tool-call flush)

This repo includes patch copies of the LiveKit library files under `patches/` to support the **filler flush** behavior (flush on tool calls).

Apply the patch to your active Python environment:

```bash
source venv/bin/activate
chmod +x ./scripts/apply_livekit_patches.sh
./scripts/apply_livekit_patches.sh
```

Then restart the agent.

### Available Commands
- "What time is it?"
- "What's the weather in Tokyo?"
- "Calculate 25 times 4"
- "Set a reminder to call mom in 30 minutes"

## Architecture

```
User Speech → Deepgram STT → OpenAI LLM → ElevenLabs TTS → Audio Output
                                ↓
                          Tool Calling
                                ↓
                         Metrics Collection
                                ↓
                           Supabase DB
```

## License

MIT

