"""Deterministic stand-ins for the LLM tasks, so the whole pipeline runs without a model.

The output has exactly the shape a model must return in live mode, and it passes the same checks.
Texts say plainly that they are demo narration; variety comes from a seed derived from the topic.
"""
import hashlib
import random

INTRO = [
    "What does it take to turn {topic} into a story worth telling? This short film follows the people, "
    "the setbacks and the turning point behind it, in a few minutes and without the usual myths.",
    "Some stories look simple from far away. {topic} is one of them, until you look at the people, "
    "the setbacks and the turning point that made it happen. This short film does exactly that.",
]
BODY = [
    ("beginning", "It started with an idea that sounded almost too ambitious. The people behind {topic} had "
     "little money, no proven method and a deadline nobody believed in. What they did have was a clear "
     "picture of the result, and the patience to explain it again and again to anyone who would listen."),
    ("setbacks", "The first attempts went badly. Equipment broke, plans had to be redrawn, and the press "
     "called the whole effort a waste. Each of those setbacks taught the team something specific, and "
     "they wrote it down, which later turned out to matter more than any single success."),
    ("method", "The work itself was slow and careful. Every step was tested on a small scale before it "
     "was tried for real, and the results were compared with what the plan had predicted. When the "
     "numbers disagreed, the plan changed, not the numbers."),
    ("turning point", "Then came the turning point. A small change in approach, suggested by someone at "
     "the edge of the project, solved the problem that had blocked everyone for months. Within weeks, "
     "what had looked impossible became routine."),
    ("what changed", "Looking back, what changed was not only the technology. {topic} changed what people "
     "expected to be possible, and it set a pattern that later projects copied: test early, keep "
     "records, and listen to the quiet voices in the room."),
    ("legacy", "Today the details are mostly forgotten, but the result is everywhere. Much of what came "
     "after was built on the same stubborn method, and on the lessons from those early failures."),
]
OUTRO = [
    "Thanks for watching this demo film about {topic}. In a real run every claim here would come from the "
    "sources listed in the description, and a fact check would compare the two.",
]
SOURCES = [
    {"id": 1, "title": "Demo source A: an overview of {topic}", "url": "https://example.org/demo/a"},
    {"id": 2, "title": "Demo source B: the people behind {topic}", "url": "https://example.org/demo/b"},
]
VISUALS = ["wide establishing view", "hands at work, close up", "old map on a desk", "machinery in motion",
           "a crowd waiting", "sunrise over the water", "notebook with calculations", "workshop at night"]


def _rng(*parts: str) -> random.Random:
    return random.Random(hashlib.sha256("\x00".join(parts).encode()).hexdigest())


def script(topic: str) -> dict:
    rng = _rng("script", topic)
    body = rng.sample(BODY, 5)
    paragraphs = [{"role": "intro", "text": rng.choice(INTRO).format(topic=topic), "source_ids": []}]
    for i, (_, text) in enumerate(body):
        paragraphs.append({"role": "body", "text": text.format(topic=topic), "source_ids": [1 + i % 2]})
    paragraphs.append({"role": "outro", "text": OUTRO[0].format(topic=topic), "source_ids": []})
    sources = [{**s, "title": s["title"].format(topic=topic)} for s in SOURCES]
    return {"sources": sources, "paragraphs": paragraphs}


def storyboard(paragraphs: list[dict], ai_share_max: float) -> dict:
    total = sum(p["duration_s"] for p in paragraphs)
    ai_budget = ai_share_max * total
    shots = []
    for p in paragraphs:
        rng = _rng("storyboard", str(p["idx"]), p["text"])
        n = 2 if p["duration_s"] < 10 else 3
        base = round(p["duration_s"] / n, 3)
        lengths = [base] * (n - 1) + [round(p["duration_s"] - base * (n - 1), 3)]
        for length in lengths:
            kind = "ai" if len(shots) % 3 == 1 and length <= ai_budget else "still"
            if kind == "ai":
                ai_budget -= length
            visual = rng.choice(VISUALS)
            shots.append({"paragraph": p["idx"], "kind": kind, "duration_s": length,
                          "prompt": f"{visual}, documentary style, natural light", "query": visual})
    return {"shots": shots}


def packaging(topic: str, script_text: str) -> dict:
    lower = script_text.lower()
    candidates = [
        (f"{topic}: the turning point", "the turning point"),
        (f"Why {topic} almost failed", "setbacks"),
        (f"{topic} and what changed", "what changed"),
        (f"The quiet method behind {topic}", "test early"),
        (f"{topic}, in a few minutes", "in a few minutes"),
        (f"{topic}: a demo film", "demo film"),
    ]
    titles = [{"text": t, "quote": q} for t, q in candidates if q in lower][:3]
    description = (f"A short documentary about {topic}. Demo run: the narration, images and voice were generated "
                   f"offline to show how the pipeline works.")
    return {"titles": titles, "description": description}
