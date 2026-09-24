"""Client footage keeps its words, timing, and optional speech."""
from __future__ import annotations

import os
import sys
import io
import tempfile

try:
    import pytest
except ImportError:
    class MonkeyPatch:
        def __init__(self):
            self._undo = []
        def setattr(self, target, name, value):
            orig = getattr(target, name)
            self._undo.append((target, name, orig))
            setattr(target, name, value)
        def undo(self):
            for target, name, orig in reversed(self._undo):
                setattr(target, name, orig)
            self._undo.clear()

    class _PytestShim:
        MonkeyPatch = MonkeyPatch
        @staticmethod
        def approx(val, tolerance=1e-2):
            class _Approx:
                def __eq__(self, other):
                    return abs(val - other) <= tolerance
            return _Approx()
    pytest = _PytestShim()

from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "prism_terminal"))
venv_pkgs = os.path.join(ROOT, ".venv", "lib", "python3.11", "site-packages")
if os.path.isdir(venv_pkgs) and venv_pkgs not in sys.path:
    sys.path.append(venv_pkgs)

from core import agents, automation, footage  # noqa: E402


def test_caption_json_is_found_after_a_newer_audio_reply():
    replies = [
        "Your audio file is ready.",
        '{"scenes":[{"seconds":2,"caption":"Precision at every stage",'
        '"voiceover":"From roughing to finishing."},'
        '{"seconds":3,"caption":"A smoother finish",'
        '"voiceover":"Made for consistent results."}]}',
    ]
    assert automation._footage_script(replies) == [
        {"text": "Precision at every stage", "seconds": 2},
        {"text": "A smoother finish", "seconds": 3},
    ]


def test_caption_json_extracts_motion_graphics_fields():
    replies = [
        '{"scenes":[{"seconds":3.5,"kicker":"01 // OVERVIEW",'
        '"caption":"High speed precision machining for aerospace.",'
        '"sub":"Tolerances under 5 microns.",'
        '"highlight":"precision","transition":"smoothleft",'
        '"style":"creator","position":"upper",'
        '"voiceover":"Every micron counts in aerospace manufacturing."}]}',
    ]
    extracted = automation._footage_script(replies)
    assert len(extracted) == 1
    assert extracted[0]["text"] == "High speed precision machining for aerospace."
    assert extracted[0]["kicker"] == "01 // OVERVIEW"
    assert extracted[0]["highlight"] == "precision"
    assert extracted[0]["transition"] == "smoothleft"
    assert extracted[0]["sub"] == "Tolerances under 5 microns."
    assert extracted[0]["style"] == "creator"
    assert extracted[0]["position"] == "upper"


def test_caption_windows_propagate_styles_and_positions():
    raw_scenes = [
        {"text": "Boring", "sub": "subtitles", "style": "creator", "position": "center", "seconds": 2.5},
        {"text": "But if you do", "sub": "the math", "style": "editorial", "position": "upper", "seconds": 3.0},
        {"text": "What do", "sub": "", "style": "neon", "position": "lower", "seconds": 2.0},
    ]
    windows = footage._caption_windows(raw_scenes, 7.5)
    assert len(windows) == 3
    assert windows[0]["style"] == "creator"
    assert windows[0]["position"] == "center"
    assert windows[0]["sub"] == "subtitles"
    assert windows[1]["style"] == "editorial"
    assert windows[1]["position"] == "upper"
    assert windows[1]["sub"] == "the math"
    assert windows[2]["style"] == "neon"
    assert windows[2]["position"] == "lower"


def test_motion_caption_archetypes_render():
    for style, text, sub in [
        ("creator", "STOP MAKING", "Boring subtitles"),
        ("editorial", "But if you do", "the math"),
        ("neon", "FOCUS PULSE", "Real-time accuracy"),
    ]:
        path = footage._render_motion_caption_card(
            text,
            sub=sub,
            kicker="01 // PRO",
            highlight=text.split()[0],
            style=style,
            scene_index=1,
        )
        try:
            with Image.open(path) as card:
                assert card.mode == "RGBA"
                assert card.width <= 1040
                assert card.height <= 400
                alpha_extrema = card.getextrema()[3]
                assert alpha_extrema[1] > 200
        finally:
            if os.path.exists(path):
                os.unlink(path)


def test_a_task_instruction_is_never_used_as_video_copy():
    reply = ('{"scenes":[{"seconds":3,"caption":'
             '"I want to make an Instagram reel for this client"}]}')
    assert automation._footage_script([reply]) == []


def test_elevenlabs_receives_spoken_copy_not_json_or_directions():
    reply = ('{"scenes":[{"kicker":"STEP 1","headline":"Built for control",'
             '"support":"Smooth material removal.",'
             '"voiceover":"From roughing to finishing, one tool performs."}]}')
    spoken = automation._voiceover_text([reply])
    assert spoken == "From roughing to finishing, one tool performs."
    assert "voiceover" not in spoken
    assert "STEP 1" not in spoken


def test_elevenlabs_uses_its_speech_form_runner():
    assert agents.AGENT_REGISTRY["ElevenLabs"]["runner"] == "elevenlabs"


def test_caption_windows_fill_the_completed_video():
    windows = footage._caption_windows([
        {"text": "First", "seconds": 2},
        {"text": "Second", "seconds": 3},
    ], 10.0)
    assert windows == [
        {"text": "First", "start": 0.0, "end": 4.0, "kicker": "", "highlight": "", "transition": ""},
        {"text": "Second", "start": 4.0, "end": 10.0, "kicker": "", "highlight": "", "transition": ""},
    ]


def test_caption_art_is_a_compact_card_not_a_full_static_frame():
    path = footage._title_overlay("Precision begins with the right tool",
                                  footage._font_path())
    try:
        with Image.open(path) as card:
            assert card.width < 1080
            assert card.height < 300
    finally:
        os.unlink(path)


def test_motion_caption_card_renders_kicker_and_highlights():
    path = footage._render_motion_caption_card(
        "Superior tolerances on exotic alloys.",
        font_path=footage._font_path(),
        kicker="02 // AEROSPACE",
        highlight="Superior",
        scene_index=2,
    )
    try:
        with Image.open(path) as card:
            assert card.mode == "RGBA"
            assert card.width < 1080
            assert card.height < 300
            # Ensure not all pixels are transparent
            alpha_extrema = card.getextrema()[3]
            assert alpha_extrema[1] > 200
    finally:
        os.unlink(path)


def test_curated_transitions_palette():
    assert "smoothleft" in footage.SUPPORTED_TRANSITIONS
    assert "zoomin" in footage.SUPPORTED_TRANSITIONS
    assert "wipeleft" in footage.SUPPORTED_TRANSITIONS
    assert "hblur" in footage.SUPPORTED_TRANSITIONS
    assert "dissolve" in footage.SUPPORTED_TRANSITIONS
    assert len(footage.TRANSITIONS_ROTATION) >= 4


def test_caption_changes_follow_the_shot_changes():
    windows = footage._caption_windows([
        {"text": "Setup", "seconds": 8},
        {"text": "Process", "seconds": 1},
    ], 6.58, shot_durations=[3.4, 3.4])
    assert [item["text"] for item in windows] == ["Setup", "Process"]
    assert windows[0]["start"] == 0.0
    assert windows[0]["end"] == pytest.approx(3.29)
    assert windows[1]["start"] == pytest.approx(3.29)
    assert windows[1]["end"] == 6.58


def test_model_written_timeline_ranges_are_valid_scene_durations(monkeypatch):
    """A writer's 0-4 timeline notation must not crash the client render."""
    assert footage._seconds("0-4") == 4.0
    assert footage._seconds("3–5 seconds") == 2.0
    assert footage._seconds("00:04") == 4.0

    info = {
        "one.mov": {"duration": 8.0, "created": "2026-09-17T00:00:00Z"},
        "two.mov": {"duration": 8.0, "created": "2026-09-17T00:01:00Z"},
    }
    monkeypatch.setattr(footage, "probe", lambda path: {"path": path, **info[path]})
    plan = footage.edit_plan(["one.mov", "two.mov"], captions=[
        {"text": "Opening action", "seconds": "0-4"},
        {"text": "Closing action", "seconds": "4-7"},
    ], transition_seconds=0.22)
    assert plan[0]["selected"] == pytest.approx(4.22)
    assert plan[1]["selected"] == pytest.approx(3.0)


def test_edit_plan_uses_capture_order_and_balances_long_takes(monkeypatch):
    info = {
        "late.mov": {"duration": 35.0, "created": "2026-07-27T05:15:21Z"},
        "early.mov": {"duration": 5.0, "created": "2026-07-27T04:59:55Z"},
    }
    monkeypatch.setattr(
        footage, "probe",
        lambda path: {"path": path, **info[path]})
    plan = footage.edit_plan(["late.mov", "early.mov"])
    assert [item["path"] for item in plan] == ["early.mov", "late.mov"]
    assert plan[1]["selected"] == footage.DEFAULT_SHOT_SECONDS
    assert plan[1]["start"] > 0


def test_edit_plan_respects_scene_durations(monkeypatch):
    info = {
        "s1.mov": {"duration": 10.0, "created": "2026-07-27T01:00:00Z"},
        "s2.mov": {"duration": 10.0, "created": "2026-07-27T02:00:00Z"},
    }
    monkeypatch.setattr(
        footage, "probe",
        lambda path: {"path": path, **info[path]})
    captions = [
        {"text": "First", "seconds": 2.5},
        {"text": "Second", "seconds": 4.0},
    ]
    plan = footage.edit_plan(["s1.mov", "s2.mov"], captions=captions, transition_seconds=0.35)
    assert plan[0]["selected"] == pytest.approx(2.85)  # 2.5 + 0.35 overlap
    assert plan[1]["selected"] == pytest.approx(4.0)


def test_audio_formats_from_elevenlabs_are_supported():
    assert ".mp3" in footage.AUDIO_SUFFIXES
    assert ".wav" in footage.AUDIO_SUFFIXES
    assert ".m4a" in footage.AUDIO_SUFFIXES


def test_narrated_render_never_reads_camera_audio(monkeypatch):
    """Voice-over output must contain narration, never phone-set sound."""
    fd, card = tempfile.mkstemp(suffix=".png")
    os.close(fd)
    Image.new("RGBA", (80, 40), (0, 0, 0, 180)).save(card)
    commands = []

    class FinishedProcess:
        stdout = io.StringIO("out_time_ms=3000000\n")
        stderr = io.StringIO("")

        def wait(self):
            return 0

    monkeypatch.setattr(footage, "is_video", lambda _path: True)
    monkeypatch.setattr(footage.os.path, "isfile", lambda _path: True)
    monkeypatch.setattr(footage.ffmpeg, "check_space", lambda _path: "")
    monkeypatch.setattr(footage, "probe", lambda _path: {"duration": 3.0})
    monkeypatch.setattr(footage, "edit_plan", lambda *_a, **_k: [
        {"path": "/tmp/camera.mov", "start": 0.0, "selected": 3.0}])
    monkeypatch.setattr(footage, "_prepare_clips", lambda *_a, **_k: [
        "/tmp/normalized-camera.mp4"])
    monkeypatch.setattr(footage, "_concat_prepared_clips", lambda *_a, **_k: (
        "/tmp/joined-camera.mp4", "/tmp/concat.txt"))
    monkeypatch.setattr(footage, "_render_motion_caption_card", lambda *_a, **_k: card)
    monkeypatch.setattr(footage.reel, "ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(
        footage.subprocess, "Popen",
        lambda command, **_kwargs: (commands.append(command) or FinishedProcess()))
    try:
        footage.render(["/tmp/camera.mov"], "/tmp/reel.mp4",
                       captions=[{"text": "A real action", "seconds": 3}],
                       audio_path="/tmp/narration.mp3")
    finally:
        if os.path.exists(card):
            os.unlink(card)

    command = commands[0]
    graph = command[command.index("-filter_complex") + 1]
    assert "[0:a]" not in graph
    assert "[2:a]" in graph
    assert "eval=frame" in graph
    assert "140*pow" in graph
    assert command[command.index("-map") + 1] == "[outv]"
    audio_map = command.index("[outa]")
    assert command[audio_map - 1] == "-map"


def test_edit_plan_expands_to_cover_long_voiceover(monkeypatch):
    # User has 2 short clips totaling 14s, but voiceover audio is 38s
    info = {
        "short1.mov": {"duration": 7.0, "created": "2026-07-27T01:00:00Z"},
        "short2.mov": {"duration": 7.0, "created": "2026-07-27T02:00:00Z"},
        "voice38.mp3": {"duration": 38.0, "created": ""},
    }
    monkeypatch.setattr(
        footage, "probe",
        lambda path: {"path": path, **info.get(path, {"duration": 0})})
    monkeypatch.setattr(
        footage.os.path, "isfile",
        lambda path: True)

    plan = footage.edit_plan(["short1.mov", "short2.mov"], audio_path="voice38.mp3", transition_seconds=0.35)
    assert len(plan) > 2
    total_video_dur = sum(item["selected"] for item in plan) - 0.35 * (len(plan) - 1)
    assert total_video_dur >= 37.0


def test_edit_plan_expands_to_cover_long_voiceover_even_with_few_captions(monkeypatch):
    info = {
        "short1.mov": {"duration": 7.0, "created": "2026-07-27T01:00:00Z"},
        "short2.mov": {"duration": 7.0, "created": "2026-07-27T02:00:00Z"},
        "voice38.mp3": {"duration": 38.0, "created": ""},
    }
    monkeypatch.setattr(
        footage, "probe",
        lambda path: {"path": path, **info.get(path, {"duration": 0})})
    monkeypatch.setattr(
        footage.os.path, "isfile",
        lambda path: True)

    captions = [
        {"text": "Intro", "seconds": 3.0},
        {"text": "Outro", "seconds": 3.0},
    ]
    plan = footage.edit_plan(["short1.mov", "short2.mov"], audio_path="voice38.mp3", captions=captions, transition_seconds=0.35)
    assert len(plan) > 2
    total_video_dur = sum(item["selected"] for item in plan) - 0.35 * (len(plan) - 1)
    assert total_video_dur >= 37.0



def test_voice_is_created_before_artwork_and_final_video():
    assert agents.PIPELINE_ORDER.index("content") < \
        agents.PIPELINE_ORDER.index("audio")
    assert agents.PIPELINE_ORDER.index("audio") < \
        agents.PIPELINE_ORDER.index("visual")
    assert agents.PIPELINE_ORDER.index("audio") < \
        agents.PIPELINE_ORDER.index("media")


def test_mix_audio_preserves_audio_longer_than_video(monkeypatch):
    executed_commands = []
    durations = {
        "/tmp/video.mp4": {"duration": 15.0},
        "/tmp/voice38.mp3": {"duration": 38.0},
    }
    monkeypatch.setattr(footage, "probe", lambda p: durations.get(p, {"duration": 0}))
    monkeypatch.setattr(footage.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(footage, "is_valid_audio", lambda p: True)
    monkeypatch.setattr(footage.os, "replace", lambda s, d: None)

    import subprocess
    def mock_run(cmd, *args, **kwargs):
        executed_commands.append(cmd)
        class Res:
            returncode = 0
            stderr = ""
        return Res()

    monkeypatch.setattr(footage.subprocess, "run", mock_run)

    out = footage.mix_audio("/tmp/video.mp4", "/tmp/voice38.mp3")
    assert out == "/tmp/video.mp4"
    assert len(executed_commands) == 1
    cmd = executed_commands[0]
    # Check that -t is set to the full 38.0s (not truncated to 15s)
    t_idx = cmd.index("-t")
    assert cmd[t_idx + 1] == "38.000"
    # Check that tpad filter is used to clone-pad the final frame
    graph_idx = cmd.index("-filter_complex")
    graph = cmd[graph_idx + 1]
    assert "tpad=stop_mode=clone" in graph


def test_mix_audio_when_video_is_longer(monkeypatch):
    executed_commands = []
    durations = {
        "/tmp/video.mp4": {"duration": 20.0},
        "/tmp/voice10.mp3": {"duration": 10.0},
    }
    monkeypatch.setattr(footage, "probe", lambda p: durations.get(p, {"duration": 0}))
    monkeypatch.setattr(footage.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(footage, "is_valid_audio", lambda p: True)
    monkeypatch.setattr(footage.os, "replace", lambda s, d: None)

    import subprocess
    def mock_run(cmd, *args, **kwargs):
        executed_commands.append(cmd)
        class Res:
            returncode = 0
            stderr = ""
        return Res()

    monkeypatch.setattr(footage.subprocess, "run", mock_run)

    out = footage.mix_audio("/tmp/video.mp4", "/tmp/voice10.mp3")
    assert out == "/tmp/video.mp4"
    assert len(executed_commands) == 1
    cmd = executed_commands[0]
    t_idx = cmd.index("-t")
    assert cmd[t_idx + 1] == "20.000"
    # Stream-copy video when video is already longer or equal
    c_idx = cmd.index("-c:v")
    assert cmd[c_idx + 1] == "copy"


def test_mix_audio_real_ffmpeg_execution():
    import subprocess
    vid_path = "/tmp/test_unit_vid.mp4"
    aud_path = "/tmp/test_unit_aud.mp3"
    for p in (vid_path, aud_path):
        if os.path.exists(p):
            os.remove(p)

    # 2-second video, 5-second audio
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=2",
        "-c:v", "libx264", vid_path
    ], check=True, capture_output=True)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "sine=f=440:d=5",
        "-c:a", "mp3", aud_path
    ], check=True, capture_output=True)

    try:
        mixed = footage.mix_audio(vid_path, aud_path)
        assert mixed == vid_path
        probe_res = subprocess.run([
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", mixed
        ], capture_output=True, text=True)
        dur = float(probe_res.stdout.strip())
        assert dur >= 4.9, f"Expected output >= 4.9s, got {dur}"
    finally:
        for p in (vid_path, aud_path):
            if os.path.exists(p):
                os.remove(p)


def test_studio_scenes_scale_to_match_long_voiceover(monkeypatch):
    monkeypatch.setattr(footage, "probe", lambda p: {"duration": 38.0})
    monkeypatch.setattr(footage.os.path, "isfile", lambda p: True)

    spec = {
        "scenes": [
            {"seconds": 4.0, "type": "intro"},
            {"seconds": 4.0, "type": "features"},
            {"seconds": 4.0, "type": "proof"},
            {"seconds": 4.0, "type": "outro"},
        ]
    }
    voice_files = [{"path": "/tmp/voice38.mp3", "kind": "audio"}]

    voice_dur = float(footage.probe(voice_files[-1]["path"]).get("duration") or 0)
    assert voice_dur == 38.0
    planned_secs = sum(float(sc.get("seconds", 4)) for sc in spec["scenes"])
    assert planned_secs == 16.0
    scale = voice_dur / planned_secs
    for sc in spec["scenes"]:
        sc["seconds"] = round(sc["seconds"] * scale, 2)

    total_scaled = sum(sc["seconds"] for sc in spec["scenes"])
    assert total_scaled == pytest.approx(38.0)
    assert all(sc["seconds"] == 9.5 for sc in spec["scenes"])


def test_ensure_active_window_recovers_when_current_window_closed():
    from unittest.mock import MagicMock
    driver = MagicMock()
    driver.window_handles = ["win1", "win2"]
    type(driver).current_window_handle = MagicMock(side_effect=Exception("no such window: target window already closed"))
    assert automation._ensure_active_window(driver) is True
    driver.switch_to.window.assert_called_with("win2")


def test_ensure_active_window_when_handles_empty():
    from unittest.mock import MagicMock
    driver = MagicMock()
    driver.window_handles = []
    driver.switch_to.new_window.side_effect = lambda t: setattr(driver, "window_handles", ["new_tab"])
    assert automation._ensure_active_window(driver) is True
    driver.switch_to.new_window.assert_called_with("tab")


def test_candidate_inputs_prioritizes_composer_over_avatar():
    from unittest.mock import MagicMock
    driver = MagicMock()
    avatar_inp = MagicMock()
    avatar_inp.get_attribute.side_effect = lambda attr: "avatar_file" if attr == "name" else None
    composer_inp = MagicMock()
    composer_inp.get_attribute.side_effect = lambda attr: "true" if attr == "multiple" else None
    driver.execute_script.side_effect = lambda script, el: True if el == composer_inp else False
    inputs = [avatar_inp, composer_inp]
    sorted_inputs = automation._candidate_inputs(driver, inputs)
    assert sorted_inputs[0] == composer_inp


def test_verify_page_attachments_detects_matching_filenames():
    from unittest.mock import MagicMock
    driver = MagicMock()
    driver.execute_script.return_value = {
        "matched_names": ["video1.mp4"],
        "chips_count": 1,
        "has_busy": False,
        "error_msg": ""
    }
    count, names, err = automation._verify_page_attachments(driver, ["video1.mp4"], timeout=0.1)
    assert count == 1
    assert names == ["video1.mp4"]
    assert err == ""


def test_verify_page_attachments_detects_error_alert():
    from unittest.mock import MagicMock
    driver = MagicMock()
    driver.execute_script.return_value = {
        "matched_names": [],
        "chips_count": 0,
        "has_busy": False,
        "error_msg": "File size exceeds 512MB limit"
    }
    count, names, err = automation._verify_page_attachments(driver, ["giant.mp4"], timeout=0.1)
    assert count == 0
    assert err == "File size exceeds 512MB limit"


def test_upload_files_returns_zero_when_dom_has_no_attachments(monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setattr(automation, "_verify_page_attachments", lambda *args, **kwargs: (0, [], ""))
    monkeypatch.setattr(os.path, "isfile", lambda p: True)
    driver = MagicMock()
    file_input = MagicMock()
    file_input.get_attribute.return_value = None
    driver.find_elements.return_value = [file_input]
    driver.execute_script.return_value = False

    agent_cfg = {"upload_selector": "input[type='file']", "upload_wait": 0.1}
    attachments = [{"path": "/fake/path/clip.mp4", "name": "clip.mp4", "size": 1024}]
    res = automation._upload_files(driver, agent_cfg, attachments, agent_name="ChatGPT")
    assert res == 0


def test_upload_files_succeeds_when_dom_verifies_attachments(monkeypatch):
    from unittest.mock import MagicMock
    monkeypatch.setattr(automation, "_verify_page_attachments", lambda *args, **kwargs: (1, ["clip.mp4"], ""))
    monkeypatch.setattr(os.path, "isfile", lambda p: True)
    driver = MagicMock()
    file_input = MagicMock()
    file_input.get_attribute.return_value = None
    driver.find_elements.return_value = [file_input]
    driver.execute_script.return_value = False

    agent_cfg = {"upload_selector": "input[type='file']", "upload_wait": 0.1}
    attachments = [{"path": "/fake/path/clip.mp4", "name": "clip.mp4", "size": 1024}]
    res = automation._upload_files(driver, agent_cfg, attachments, agent_name="ChatGPT")
    assert res == 1


def test_join_clips_with_transitions_builds_xfade_chain(monkeypatch):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        target = cmd[-1]
        with open(target, "wb") as f:
            f.write(b"x" * 2048)

        class Res:
            returncode = 0
            stderr = ""
        return Res()

    monkeypatch.setattr(footage.subprocess, "run", fake_run)
    monkeypatch.setattr(footage.reel, "ffmpeg_path", lambda: "ffmpeg")
    monkeypatch.setattr(footage.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(footage.os.path, "getsize", lambda p: 2048)

    joined, _ = footage._join_clips_with_transitions(
        ["/tmp/c1.mp4", "/tmp/c2.mp4", "/tmp/c3.mp4"],
        durations=[3.0, 3.0, 3.0],
        transitions=["smoothleft", "zoomin"],
        trans_dur=0.22,
        out_path="/tmp/output.mp4"
    )
    assert len(calls) == 1
    cmd = calls[0]
    filter_graph = cmd[cmd.index("-filter_complex") + 1]
    assert "xfade=transition=smoothleft:duration=0.220:offset=2.780" in filter_graph
    assert "xfade=transition=zoomin:duration=0.220:offset=5.560" in filter_graph
    if os.path.exists(joined):
        try:
            os.unlink(joined)
        except OSError:
            pass


if __name__ == "__main__":
    import inspect
    mp = MonkeyPatch() if 'MonkeyPatch' in globals() else None
    tests = [f for name, f in sorted(globals().items()) if name.startswith("test_") and callable(f)]
    passed = 0
    for test in tests:
        sig = inspect.signature(test)
        try:
            if "monkeypatch" in sig.parameters:
                test(mp)
            else:
                test()
            passed += 1
            print(f"PASS: {test.__name__}")
        except Exception as e:
            print(f"FAIL: {test.__name__} - {e}")
            raise
        finally:
            if mp:
                mp.undo()
    print(f"\nAll {passed} tests passed successfully!")
