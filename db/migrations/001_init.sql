-- Pipeline state. One row per video; shots are the visual pieces of a video.
CREATE TABLE videos (
  id             bigserial PRIMARY KEY,
  topic          text NOT NULL CHECK (length(topic) BETWEEN 3 AND 200),
  notes          text,
  mode           text NOT NULL DEFAULT 'demo' CHECK (mode IN ('demo', 'live')),
  status         text NOT NULL DEFAULT 'queued' CHECK (status IN
                   ('queued', 'script', 'voice', 'storyboard', 'production', 'assembly', 'packaging', 'ready', 'failed')),
  script         jsonb,
  voice          jsonb,
  srt_path       text,
  music_path     text,
  final_path     text,
  final_qc       jsonb,
  thumbnail_path text,
  title          text,
  title_options  jsonb,
  description    text,
  attempts       int NOT NULL DEFAULT 0,
  last_error     text,
  render_job     text,
  locked_until   timestamptz,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX videos_runnable ON videos (status, locked_until);

CREATE TABLE shots (
  id          bigserial PRIMARY KEY,
  video_id    bigint NOT NULL REFERENCES videos(id) ON DELETE CASCADE,
  idx         int NOT NULL,
  paragraph   int NOT NULL,
  kind        text NOT NULL CHECK (kind IN ('ai', 'still')),
  start_s     numeric(8,3) NOT NULL,
  duration_s  numeric(6,3) NOT NULL CHECK (duration_s > 0),
  prompt      text,
  query       text,
  status      text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'generating', 'done', 'fallback', 'failed')),
  attempts    int NOT NULL DEFAULT 0,
  job_id      text,
  image_path  text,
  asset_path  text,
  qc          jsonb,
  source      jsonb,
  updated_at  timestamptz NOT NULL DEFAULT now(),
  UNIQUE (video_id, idx)
);
CREATE INDEX shots_work ON shots (status, updated_at);

CREATE TABLE costs (
  id          bigserial PRIMARY KEY,
  video_id    bigint REFERENCES videos(id) ON DELETE CASCADE,
  shot_id     bigint,
  provider    text NOT NULL,
  model       text NOT NULL,
  usd         numeric(10,4) NOT NULL DEFAULT 0,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE stage_log (
  id          bigserial PRIMARY KEY,
  video_id    bigint REFERENCES videos(id) ON DELETE CASCADE,
  stage       text NOT NULL,
  ok          boolean NOT NULL,
  detail      text,
  created_at  timestamptz NOT NULL DEFAULT now()
);
