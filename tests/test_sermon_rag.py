import json
from pathlib import Path

from core.sermon_rag import build_sermon_context, promote_approved_reviews


def _write_review(output: Path, *, approved=True):
    review = output / "pastor.review.json"
    review.write_text(json.dumps({
        "schema": "kairos.theology-review.v1",
        "title": "전수 승인",
        "claims": [
            {
                "id": "SOT-1",
                "domain": "soteriology",
                "claim": "구원은 예수 그리스도의 십자가와 부활로 주시는 은혜다.",
                "status": "approved" if approved else "pending",
                "confidence": "high",
                "evidence": ["wiki/sermons/2026-test/chunks/007.md"],
            },
            {
                "id": "ESC-1",
                "domain": "eschatology",
                "claim": "검토되지 않은 세부 주장",
                "status": "pending",
            },
        ],
    }, ensure_ascii=False), encoding="utf-8")
    return review


def _write_manifest(output: Path):
    folder = output / "distilled"
    folder.mkdir()
    (folder / "corpus-manifest.json").write_text(json.dumps({
        "schema": "kairos.sermon-corpus.v1",
        "sermons": [
            {
                "article": "2026-test",
                "date": "2026-04-05",
                "title": "죽음을 이긴 부활의 승리",
                "passage": "고린도전서 15:20",
                "summary": "예수 그리스도의 부활로 사망에서 생명으로 옮겨진다.",
                "definition_evidence": [{
                    "marker": "W2",
                    "path": "wiki/sermons/2026-test/chunks/007.md",
                    "excerpt": "구원이란 십자가와 부활로 사망에서 생명으로 옮겨지는 은혜입니다.",
                }],
            },
            {
                "article": "2025-other",
                "date": "2025-01-01",
                "title": "찬양",
                "passage": "시편 150:1",
                "summary": "호흡이 있는 자마다 찬양한다.",
                "definition_evidence": [],
            },
        ],
    }, ensure_ascii=False), encoding="utf-8")
    (folder / "fingerprint.json").write_text(json.dumps({
        "schema": "kairos.sermon-fingerprint.v1",
        "n_docs": 93,
        "n_sents": 1000,
        "sent_words": {"p50": 10.0, "p90": 20.0},
        "punct_per_1k": {"question": 1.0, "exclam": 0.2},
        "para": {"sents_p50": 2.0},
    }), encoding="utf-8")


def test_promote_includes_only_explicit_approvals(tmp_path):
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    workspace.mkdir()
    output.mkdir()
    _write_review(output)

    result = promote_approved_reviews(str(workspace), str(output))

    assert result["approved"] == 1
    profile = json.loads(Path(result["profile_path"]).read_text(encoding="utf-8"))
    assert [claim["id"] for claim in profile["claims"]] == ["SOT-1"]
    theology = Path(result["theology_path"]).read_text(encoding="utf-8")
    assert "SOT-1" in theology
    assert "ESC-1" not in theology


def test_sermon_context_retrieves_marker_evidence(tmp_path):
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    workspace.mkdir()
    output.mkdir()
    _write_review(output)
    _write_manifest(output)

    block, count = build_sermon_context(
        "고린도전서 15장 부활 설교를 기획해줘",
        str(workspace),
        str(output),
    )

    assert count >= 2
    assert "목사님 승인 신학" in block
    assert "SOT-1" in block
    assert "W2" in block
    assert "죽음을 이긴 부활의 승리" in block
    assert "분석 설교 93편" in block
    assert "검토되지 않은 세부 주장" not in block


def test_sermon_context_is_empty_without_approval(tmp_path):
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    workspace.mkdir()
    output.mkdir()
    _write_review(output, approved=False)
    _write_manifest(output)

    assert build_sermon_context(
        "부활 설교 기획", str(workspace), str(output)
    ) == ("", 0)


def test_manual_theology_profile_is_not_overwritten(tmp_path):
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    author = workspace / "authors" / "main_pastor"
    author.mkdir(parents=True)
    output.mkdir()
    original = "manual: true\n"
    (author / "theology.yaml").write_text(original, encoding="utf-8")
    _write_review(output)

    result = promote_approved_reviews(str(workspace), str(output))

    assert (author / "theology.yaml").read_text(encoding="utf-8") == original
    assert Path(result["theology_path"]).name == "theology.approved.yaml"


def test_sermon_context_prefers_widest_corpus_over_newest_subset(tmp_path):
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    workspace.mkdir()
    output.mkdir()
    _write_review(output)
    _write_manifest(output)

    subset = output / "newer-subset"
    subset.mkdir()
    (subset / "fingerprint.json").write_text(json.dumps({
        "n_docs": 12,
        "n_sents": 120,
        "sent_words": {"p50": 8.0, "p90": 16.0},
        "punct_per_1k": {"question": 0.5, "exclam": 0.1},
        "para": {"sents_p50": 3.0},
    }), encoding="utf-8")
    (subset / "corpus-manifest.json").write_text(json.dumps({
        "sermons": [{
            "article": "subset-only",
            "date": "2026-07-01",
            "title": "부분 자료",
            "passage": "",
            "summary": "",
            "definition_evidence": [],
        }],
    }, ensure_ascii=False), encoding="utf-8")

    block, _ = build_sermon_context(
        "고린도전서 15장 부활 설교 기획", str(workspace), str(output)
    )

    assert "분석 설교 93편" in block
    assert "죽음을 이긴 부활의 승리" in block
    assert "부분 자료" not in block


def test_historical_verified_claims_are_lower_priority_rag_not_theology(tmp_path):
    workspace = tmp_path / "workspace"
    output = tmp_path / "output"
    workspace.mkdir()
    output.mkdir()
    _write_review(output)
    _write_manifest(output)
    (output / "historical.review.json").write_text(json.dumps({
        "schema": "kairos.theology-review.v1",
        "review_mode": "historical",
        "title": "과거 설교 확인",
        "claims": [{
            "id": "HIST-1",
            "domain": "christology",
            "principle_type": "theology",
            "claim": "과거 설교에서 부활은 죽음을 이긴 생명이라고 선포했다.",
            "status": "historical_verified",
            "confidence": "high",
            "years": [2020, 2025],
            "evidence": ["wiki/sermons/2020-test/chunks/001.md"],
        }],
    }, ensure_ascii=False), encoding="utf-8")

    promoted = promote_approved_reviews(str(workspace), str(output))
    profile = json.loads(Path(promoted["profile_path"]).read_text(encoding="utf-8"))
    theology = Path(promoted["theology_path"]).read_text(encoding="utf-8")
    block, count = build_sermon_context(
        "부활 설교 기획", str(workspace), str(output)
    )

    assert promoted["approved"] == 1
    assert promoted["historical"] == 1
    assert profile["historical_count"] == 1
    assert profile["historical_claims"][0]["id"] == "HIST-1"
    assert "HIST-1" not in theology
    assert "현재 확정 원칙보다 낮은 우선순위" in block
    assert "HIST-1" in block
    assert count >= 3
