"""Sound in motion: events in the composition, placement from measured sync points, the -14 LUFS master and the muxed MP4."""
import shutil

import numpy as np
import pytest
from pydantic import ValidationError

from vitruvius_hoard import sound
from vitruvius_hoard.motion import SOUND_ROLES, Composition, templates

ENGINE = sound.status()["available"]
needs_engine = pytest.mark.skipif(not ENGINE, reason="the sound engine is not installed (pip install earshot, see sound.py)")
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg/ffprobe not on PATH")


def composition(**sound_fields):
    base = templates()["launch"]
    return Composition.model_validate({**base, "sound": sound_fields})


# ---------------------------------------------------------------- the model and the plan (no engine needed)

def test_sound_is_off_and_optional_by_default():
    c = Composition.model_validate(templates()["launch"])
    assert c.sound.enabled is False and c.sound.events == []
    # a composition saved before sound existed has no key and still validates
    body = c.model_dump()
    body.pop("sound")
    assert Composition.model_validate(body).sound.enabled is False


def test_events_are_validated():
    ok = composition(enabled=True, events=[{"t": 1.5, "rol": "hit"}, {"t": 4, "rol": "bell", "gain_db": -3}])
    assert [e.rol for e in ok.sound.events] == ["hit", "bell"]
    with pytest.raises(ValidationError):
        composition(events=[{"t": 1, "rol": "laser"}])                      # a role the kit does not have
    with pytest.raises(ValidationError):
        composition(events=[{"t": 99, "rol": "hit"}])                       # after the end (the launch template lasts 10 s)
    with pytest.raises(ValidationError):
        composition(events=[{"t": 1, "rol": "hit", "extra": 1}])
    with pytest.raises(ValidationError):
        composition(preset="loud")


def test_plan_has_auto_cues_and_the_users_events_in_time_order():
    c = composition(enabled=True, events=[{"t": 2.0, "rol": "hit"}])
    events = sound.plan(c)
    assert [e["t"] for e in events] == sorted(e["t"] for e in events)
    assert any(e["source"] == "user" and e["rol"] == "hit" and e["t"] == 2.0 for e in events)
    assert sum(1 for e in events if e["rol"] == "whoosh.short") == 2        # three scenes: two changes
    assert any(e["rol"] == "text" for e in events) and any(e["rol"] == "pop" for e in events)
    assert sound.plan(c) == events                                          # deterministic
    only_user = sound.plan(composition(enabled=True, auto=False, events=[{"t": 2.0, "rol": "hit"}]))
    assert [e["rol"] for e in only_user] == ["hit"]


def test_roles_match_the_installed_bank():
    if not ENGINE:
        pytest.skip("engine not installed")
    assert tuple(sound.status()["roles"]) == SOUND_ROLES
    assert set(sound.status()["presets"]) == {"calm", "crisp", "minimal", "launch"}


def test_without_the_engine_the_error_says_how_to_install(monkeypatch):
    monkeypatch.setattr(sound, "_engine", lambda: (_ for _ in ()).throw(sound.SoundUnavailable("The sound engine is not installed (x). " + sound.INSTALL_HINT)))
    state = sound.status()
    assert state["available"] is False and "pip install" in state["hint"]


# ---------------------------------------------------------------- the master (no engine needed beyond pyloudnorm)

def test_master_reaches_minus_14_lufs_under_the_ceiling():
    pytest.importorskip("pyloudnorm")
    sr = 48000
    mix = np.zeros((sr * 6, 2))
    for at in (0.5, 2.0, 3.5, 5.0):                       # sparse effects, quiet between them: the ceiling has to work for it
        n = int(0.25 * sr)
        t = np.arange(n) / sr
        burst = np.sin(2 * np.pi * 800 * t) * np.exp(-t * 18)
        mix[int(at * sr):int(at * sr) + n] += burst[:, None] * 0.2
    out, info = sound.master(mix)
    assert info["reached"], info
    assert abs(info["lufs"] - sound.TARGET_LUFS) <= sound.LOUDNESS_TOLERANCE
    assert info["true_peak_dbtp"] <= sound.CEILING_DBTP + 0.05
    assert out.shape == mix.shape


def test_master_never_breaks_the_ceiling_even_when_the_target_cannot_be_reached():
    pytest.importorskip("pyloudnorm")
    sr = 48000
    mix = np.zeros((sr * 6, 2))
    mix[sr * 2:sr * 2 + 48] = 0.5                                   # one 1 ms click in six seconds: -14 LUFS would need absurd limiting
    out, info = sound.master(mix)
    assert info["true_peak_dbtp"] <= sound.CEILING_DBTP + 0.05
    assert info["reached"] is False                                  # said honestly, not pretended
    silent, quiet = sound.master(np.zeros((sr, 2)))
    assert quiet["lufs"] is None and quiet["reached"] is False and not silent.any()


# ---------------------------------------------------------------- placement, measured on the finished track

def _onset_s(track, sr, after, before=0.2, floor_db=-30):
    mono = np.max(np.abs(track), axis=1)
    a, b = int((after - before) * sr), int((after + 0.4) * sr)
    seg = mono[a:b]
    return (a + int(np.nonzero(seg >= seg.max() * 10 ** (floor_db / 20))[0][0])) / sr


@needs_engine
def test_each_sound_lands_on_its_cue_within_a_few_milliseconds(tmp_path):
    import soundfile as sf
    c = composition(enabled=True, preset="crisp", auto=False, events=[{"t": 1.0, "rol": "hit"}, {"t": 3.0, "rol": "pop"}, {"t": 5.0, "rol": "click"}])
    out = sound.mix(c, tmp_path, tmp_path / "mix.wav")
    assert out["ok"] and not out["silent"] and len(out["events"]) == 3
    audio, sr = sf.read(out["file"], always_2d=True)
    assert sr == 48000 and audio.shape[1] == 2
    assert len(audio) == round(sum(s.duration for s in c.scenes) * c.fps / c.fps * sr)     # exactly the length of the picture
    for e in out["events"]:
        measured = _onset_s(audio, sr, e["expected_s"])                                     # measured here, not taken from the lock
        assert abs(measured - e["expected_s"]) <= 0.010, (e["rol"], measured, e["expected_s"])
        assert e["error_ms"] is not None and abs(e["error_ms"]) <= 10                       # the take as placed
        assert e["in_mix_error_ms"] is not None and abs(e["in_mix_error_ms"]) <= 10         # and found again in the finished track
    assert out["max_error_ms"] <= 10
    assert abs(out["loudness"]["lufs"] - sound.TARGET_LUFS) <= sound.LOUDNESS_TOLERANCE
    assert out["loudness"]["true_peak_dbtp"] <= sound.CEILING_DBTP + 0.05


@needs_engine
def test_a_peak_aligned_whoosh_puts_its_loudest_moment_on_the_cue(tmp_path):
    import soundfile as sf
    c = composition(enabled=True, preset="launch", auto=False, events=[{"t": 4.0, "rol": "whoosh.short"}])
    out = sound.mix(c, tmp_path, tmp_path / "whoosh.wav")
    e = out["events"][0]
    assert e["align"] == "peak" and e["offset_ms"] == 37.0                                   # the launch preset lands whoosh peaks after the cut
    audio, sr = sf.read(out["file"], always_2d=True)
    win = int(0.005 * sr)
    smooth = np.convolve(np.max(np.abs(audio), axis=1), np.ones(win) / win, mode="same")
    peak_s = int(np.argmax(smooth)) / sr
    assert abs(peak_s - (4.0 + 0.037)) <= 0.010, peak_s


@needs_engine
def test_repeated_cues_take_turns_and_a_role_left_off_is_reported(tmp_path):
    c = composition(enabled=True, preset="crisp", auto=False,
                    events=[{"t": 1.0, "rol": "pop"}, {"t": 1.5, "rol": "pop"}, {"t": 2.0, "rol": "pop"}, {"t": 3.0, "rol": "riser"}])
    out = sound.mix(c, tmp_path, None)
    takes = [e["take"] for e in out["events"] if e["rol"] == "pop"]
    assert len(set(takes)) > 1                                                               # not the same sample three times
    assert out["skipped"] == [{"t": 3.0, "rol": "riser", "why": "the preset leaves this role off"}]


@needs_engine
def test_overlapping_sounds_are_checked_as_placed_not_guessed_from_the_mix(tmp_path):
    # a whoosh rises long before its peak: next to a pop, the mix cannot tell which onset is whose, so it says nothing rather than a wrong number
    c = composition(enabled=True, preset="crisp", auto=False, events=[{"t": 3.0, "rol": "pop"}, {"t": 3.0, "rol": "whoosh.short"}])
    out = sound.mix(c, tmp_path, None)
    assert len(out["events"]) == 2
    for e in out["events"]:
        assert e["in_mix_s"] is None and e["in_mix_error_ms"] is None
        assert e["error_ms"] is not None and abs(e["error_ms"]) <= 10


@needs_engine
def test_a_composition_with_no_cues_is_silent_not_an_error(tmp_path):
    c = composition(enabled=True, auto=False, events=[])
    out = sound.mix(c, tmp_path, tmp_path / "x.wav")
    assert out["silent"] is True and "file" not in out


# ---------------------------------------------------------------- the muxed MP4, read back with ffprobe

@needs_engine
@needs_ffmpeg
def test_the_mp4_carries_the_mix_with_the_right_loudness_and_timing(tmp_path):
    import numpy as np
    from vitruvius_hoard.hoard_link.media.ffmpeg import FFmpeg
    c = composition(enabled=True, preset="crisp", auto=False, events=[{"t": 1.0, "rol": "hit"}, {"t": 3.0, "rol": "pop"}])
    out = sound.mix(c, tmp_path, tmp_path / "audio.wav")
    ff = FFmpeg()
    seconds = sum(s.duration for s in c.scenes)
    movie = tmp_path / "motion.mp4"
    ff.run(["-f", "lavfi", "-i", f"color=c=black:s=320x240:d={seconds}:r={c.fps}", "-i", out["file"], "-map", "0:v:0", "-map", "1:a:0", "-c:v", "libx264",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-t", f"{seconds:.6f}", "-movflags", "+faststart", movie], timeout=120)
    info = ff.summarize(ff.probe(movie))
    assert info["has_video"] and info["has_audio"] and info["audio_codec"] == "aac" and info["sample_rate"] == 48000
    assert abs(info["duration_s"] - seconds) < 0.1
    measured = ff.loudness(movie)
    assert abs(measured["integrated_lufs"] - sound.TARGET_LUFS) <= 1.0, measured
    assert measured["true_peak_dbfs"] <= -0.5
    pcm = ff.extract_pcm(movie, rate=48000)
    samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float64) if isinstance(pcm, (bytes, bytearray)) else np.asarray(pcm, dtype=np.float64)
    track = np.stack([samples, samples], axis=1)
    for e in out["events"]:
        assert abs(_onset_s(track, 48000, e["expected_s"]) - e["expected_s"]) <= 0.035, e       # within one frame at 24 fps, after AAC


# ---------------------------------------------------------------- the tools and the API

def test_tools_are_in_the_catalogue_and_read_only_where_they_should_be():
    from vitruvius_hoard.agent_tools import TOOLS
    by_name = {t.name: t for t in TOOLS}
    assert by_name["motion_sound_plan"].annotations["readOnlyHint"] is True
    assert by_name["motion_sound_render"].annotations["readOnlyHint"] is False


def test_plan_over_http_and_through_the_tool(client):
    from vitruvius_hoard.agent_tools import call_tool
    created = client.post("/api/motions", json={"composition": {**templates()["launch"], "sound": {"enabled": True, "events": [{"t": 2, "rol": "hit"}]}}}).json()
    plan = call_tool(client.svc, "motion_sound_plan", {"id": created["id"]})
    assert plan["enabled"] is True and any(e["rol"] == "hit" for e in plan["events"]) and "engine" in plan
    over_http = client.post("/api/motions/sound/plan", json={"id": created["id"], "preset": "launch"}).json()
    assert over_http["preset"] == "launch"
    assert client.get("/api/motions/sound/status").json()["presets"]
    assert client.post("/api/motions/sound/plan", json={}).status_code == 400


@needs_engine
def test_render_over_http_returns_a_downloadable_wav(client):
    created = client.post("/api/motions", json={"composition": {**templates()["caption"], "sound": {"enabled": True, "events": [{"t": 1.0, "rol": "hit"}]}}}).json()
    out = client.post("/api/motions/sound/render", json={"id": created["id"]})
    assert out.status_code == 200, out.text
    body = out.json()
    assert abs(body["loudness"]["lufs"] - sound.TARGET_LUFS) <= sound.LOUDNESS_TOLERANCE
    wav = client.get(body["download"])
    assert wav.status_code == 200 and wav.content[:4] == b"RIFF"
