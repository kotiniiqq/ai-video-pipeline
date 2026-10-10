# ai-video-pipeline

A pipeline that turns a topic into a narrated documentary video: script with sources, voice-over,
storyboard, generated and still shots with quality checks, a mastered mp4 with subtitles, titles and
a thumbnail. n8n workflows (written in TypeScript) run the stages; a FastAPI worker does the media
work with FFmpeg and OpenCV. It runs end to end on a laptop **without any API keys**.

> Reference version of a video pipeline I am building for a client. That system is private; this
> repo rebuilds its architecture from scratch, without the client's prompts, assets or channel. In
> demo mode the narration text is generated from templates, the frames are synthetic and the voice
> is an offline TTS, so you can see every stage run without paying for anything.

## Run it

Needs Docker and Node 22+.

```bash
git clone https://github.com/kotiniiqq/ai-video-pipeline && cd ai-video-pipeline
npm ci
docker compose up -d --build     # postgres, n8n 2.40, worker (first build downloads the voice and face models)
npm run setup                    # n8n owner + API key, DB credential, deploys and publishes all workflows

curl -X POST localhost:5678/webhook/video -H 'content-type: application/json' \
     -d '{"topic": "The first transatlantic telegraph cable"}'
# {"id":1,"status":"queued","status_url":"/webhook/video-status?id=1"}

curl 'localhost:5678/webhook/video-status?id=1'
```

The video goes `queued → voice → storyboard → production → assembly → packaging → ready` in about
three minutes. Files land in the `shared` volume under `videos/<id>/`: `final.mp4`, `subtitles.srt`,
`thumbnail.jpg`, plus every shot and narration part. n8n is at http://localhost:5678
(`owner@example.com` / `Pipeline-local-1`, local only) if you want to watch the executions.

`npm run e2e` does the same run and checks the result. To see the retry and fallback paths run as
well, start the stack and the test with `DEMO_FAULTS=1`: some shots then fail on purpose.

```bash
DEMO_FAULTS=1 docker compose up -d && DEMO_FAULTS=1 npm run e2e
```

## What happens to a video

| Stage | What it does | Checked by code |
|---|---|---|
| script | the model writes 6-10 paragraphs: intro, body, outro | every body paragraph cites a source the script lists; 250-1400 words; one repair round with the errors |
| voice | each paragraph spoken separately, joined with short pauses | each paragraph gets a slot on the timeline; subtitles follow it |
| storyboard | 1-4 shots per paragraph, AI or still | durations fit the narration (model rounding ≤ 15% is scaled away), AI time capped at 30% |
| production | picture → image QC → render job → clip QC, per shot | three tries, then Ken Burns over the last picture; black, frozen or wrong-length clips are rejected |
| assembly | cuts inside a paragraph, crossfades between paragraphs, music ducked under the voice | final QC: length = narration ± 1 s, −14 ± 1 LUFS, no black frames |
| packaging | three titles, a description, a thumbnail | a title is kept only if the quote it is based on occurs in the script; sources and photo credits go into the description |

A stage that fails is retried on the next runner tick; the third failure fails the video with the
reason in `last_error`, and a notification goes out. More in [docs/architecture.md](docs/architecture.md).

## Demo and live

The worker is the only thing that talks to model providers; `MODE` in `.env` picks the implementation.

| | `MODE=demo` (default) | `MODE=live` (your keys in `.env`) |
|---|---|---|
| script, storyboard, titles | deterministic generator, same JSON shape a model must return | OpenRouter, any chat model with JSON output |
| voice | Piper, offline (LJSpeech voice, public domain) | ElevenLabs |
| AI shots | synthetic frame + FFmpeg camera move and grain | fal.ai: FLUX schnell, then image-to-video |
| stills | synthetic frames | Openverse: only PD, CC0, CC BY, CC BY-SA, at least 1024 px, with attribution |
| notifications | log line | Telegram, if a bot token and chat id are set |

Every provider response carries its cost, which is stored per video and per shot.

## Status, honestly

- **75 worker tests** (pytest, inside the worker image): QC rules on generated clips (black, frozen,
  wrong length, loudness), Ken Burns, fitting, the master render (picture and sound end together;
  −14 LUFS reached even for audio with sharp peaks), subtitles, thumbnails, background jobs including
  a job whose process died, every demo provider, and every live provider against a mock transport
  (request shapes, JSON wrapped in prose or code fences, retries on 429/5xx, missing keys).
- **92 TypeScript tests**: every Code-node module (script and storyboard checks, the shot state
  machine, stage retries, titles, segment planning), bundles run under the preamble n8n puts in
  front of every Code node, plus the deploy kit's own suite against a mock n8n API.
- **End to end on a real n8n 2.40.6** (`npm run e2e`): a video goes from the webhook to `ready`
  in about 170 s on a laptop (101 s video, 21 shots, 28 subtitle cues, −14.5 LUFS); with
  `DEMO_FAULTS=1` in about 240 s, with 7 shots retried and 1 Ken Burns fallback. CI runs all of it.
- The first end-to-end runs found what the unit tests had missed, each now pinned by a test:
  `concat` drops the frame rate, so the next `xfade` refused to start; linear loudness normalisation
  landed 1 LU short whenever speech peaks hit the true-peak ceiling; Compose built the test stage of
  the worker image instead of the service.
- **Live mode is tested against mocks only.** The request formats follow the providers'
  documentation; I have not run this repo against paid APIs.
- Not here, on purpose: YouTube upload, a music library, editing thumbnails from Telegram, a Telegram
  bot for ideas, archive photo pools captioned by a vision model.

## Layout

```
workflows/   n8n workflows in TypeScript (Workflow SDK): intake, status, runners, stages, error alert
code/        the decisions, as tested modules bundled into Code nodes
lib/         small node builders used by the workflows
kit/         build, validate and deploy for n8n (from my n8n-workflow-kit)
worker/      FastAPI service: QC, rendering, packaging, jobs, provider gateway (demo and live)
db/          schema
scripts/     setup of the local stack
e2e/         the end-to-end run
```

## How this was built

A design spec and a plan first, then test-first implementation task by task, then the end-to-end
run on a real n8n, which is where the three bugs above surfaced.

## License

MIT
