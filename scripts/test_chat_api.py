#!/usr/bin/env python3
"""
Test the chat API with Bible knowledge base integration.
"""

import json
import sys
import time
from pathlib import Path
from core import server
from core.store import Store
from core.settings import _DEFAULT_SETTINGS

# Minimal test
def test_build_prompt():
    """Test the build_prompt function with Bible refs."""
    from core.server import build_prompt

    print("Testing build_prompt() with Bible refs...")

    # Simulate a chat context with Bible search results
    rec = {
        "snippets": [],
        "avoid": [],
        "corrections": [],
        "rules": ["한글로 친근하게 답변한다"],
        "bible_refs": [
            {
                "reference": "요한복음 3:16",
                "content": "하나님이 세상을 이처럼 사랑하사 독생자를 주셨으니 이는 저를 믿는 자마다 멸망하지 않고 영생을 얻게 하려 하심이니라",
                "source": "bethel",
                "type": "bible_verse"
            },
            {
                "reference": "요한복음 3:17",
                "content": "하나님이 그 아들을 세상에 보내신 것은 세상을 심판하려 하심이 아니라 그로 말미암아 세상이 구원을 받게 하려 하심이라",
                "source": "bethel",
                "type": "bible_verse"
            }
        ]
    }

    prompt, n_recalled = build_prompt("예수님에 대해 말씀해 주세요.", rec)
    print(f"\n{'='*60}")
    print("Input:")
    print(f"  Query: '예수님에 대해 말씀해 주세요.'")
    print(f"  Bible refs: {len(rec['bible_refs'])}")
    print(f"  Rules: {len(rec['rules'])}")
    print(f"\nOutput:")
    print(f"  Prompt length: {len(prompt)} chars")
    print(f"  Recalled snippets: {n_recalled}")
    print(f"\nGenerated prompt:")
    print("-" * 60)
    print(prompt[:500])
    print("..." if len(prompt) > 500 else "")
    print("-" * 60)

    return len(prompt) > 0 and "[성경 자료 검색" in prompt


def test_document_search():
    """Test the document search function."""
    from core.documents import search

    db_path = Path("D:\\projects\\kairos-studio-v2\\bible_documents.db")
    if not db_path.exists():
        print("✗ bible_documents.db not found")
        return False

    print("\nTesting document search...")
    print(f"{'='*60}")

    test_queries = [
        "요한복음 3장 16절",
        "창조",
        "예수님의 사랑",
        "팔레스타인 지도"
    ]

    for query in test_queries:
        results = search(db_path, query, limit=2)
        print(f"\nQuery: '{query}'")
        print(f"  Results: {len(results)}")
        for r in results:
            ref = r.get('reference', '')[:40]
            content = r.get('content', '')[:60]
            print(f"    - {ref}: {content}...")

    return True


def main():
    print("Bible RAG Integration Tests")
    print("=" * 60)

    test1 = test_build_prompt()
    test2 = test_document_search()

    print(f"\n{'='*60}")
    print("Results:")
    print(f"  build_prompt() with Bible refs: {'✓ PASS' if test1 else '✗ FAIL'}")
    print(f"  document.search(): {'✓ PASS' if test2 else '✗ FAIL'}")
    print("=" * 60)

    return 0 if (test1 and test2) else 1


if __name__ == "__main__":
    sys.exit(main())
