## LiveKit Voice Monorepo

This repo contains:
- `strands-agent-server/`: Strands OpenAI-compatible streaming server (LLM + tools + filler logic)
- `livekit-agent/`: LiveKit agent worker (STT/LLM/TTS) + ElevenLabs preset matrix
- `playground/`: Next.js playground UI for testing (includes TTS preset selector)

### Quick start (local)

1) Start Strands server

```bash
cd strands-agent-server
# activate your venv and install requirements
uvicorn agents:app --host 0.0.0.0 --port 8080
```

2) Start LiveKit agent

```bash
cd livekit-agent
# activate your venv and install requirements
python agent.py start
```

3) Start Playground

```bash
cd playground
pnpm install
pnpm dev
```

Then open `http://localhost:3000`.

### Notes
- `.env.local` files are intentionally ignored. Create them locally as needed.
