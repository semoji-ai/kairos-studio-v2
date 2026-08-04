from pathlib import Path

from core.output_workspace import instruction, mirror_outputs, session_dir


def test_session_dir_is_stable_and_named_for_task(tmp_path):
    first = session_dir(str(tmp_path), 12, "하나님의 영과 마귀의 영 설교")
    second = session_dir(str(tmp_path), 12, "후속 질문")
    assert first == second
    assert first is not None
    assert first.name.startswith("session-12-하나님의-영과-마귀의-영")


def test_mirror_outputs_copies_linked_file(tmp_path):
    agent = tmp_path / "agent"
    output = tmp_path / "output"
    agent.mkdir()
    output.mkdir()
    source = agent / "draft.md"
    source.write_text("# sermon", encoding="utf-8")

    copied = mirror_outputs("[원고](draft.md)", str(agent), output)

    assert copied == [(output / "draft.md").resolve()]
    assert (output / "draft.md").read_text(encoding="utf-8") == "# sermon"


def test_instruction_contains_session_output_path(tmp_path):
    text = instruction(Path(tmp_path))
    assert str(tmp_path) in text
    assert "산출물 저장 위치" in text
