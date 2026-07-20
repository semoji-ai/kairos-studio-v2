import { useEffect, useMemo, useState } from "react";
import { bibleCoverage } from "./api";
import type { BibleBook, BibleChapter } from "./api";

/** 성경 66권 장별 설교 커버리지 체크 페이지. */
export default function BibleCoverage() {
  const [books, setBooks] = useState<BibleBook[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sel, setSel] = useState<number | null>(null);        // book num
  const [selCh, setSelCh] = useState<number | null>(null);    // chapter n

  useEffect(() => {
    bibleCoverage().then(d => setBooks(d.books)).catch(e => setError(String(e)));
  }, []);

  const book = useMemo(() => books?.find(b => b.num === sel) ?? null, [books, sel]);
  const chapter = useMemo(
    () => book?.chapters.find(c => c.n === selCh) ?? null, [book, selCh]);

  if (error) return <div style={{ padding: 24 }}>⚠️ {error}</div>;
  if (!books) return <div style={{ padding: 24 }}>커버리지 계산 중…</div>;

  const total = books.reduce((a, b) => a + b.total_chapters, 0);
  const covered = books.reduce((a, b) => a + b.covered_chapters, 0);

  const isCovered = (c: BibleChapter, v: number) =>
    c.ranges.some(([s, e]) => v >= s && v <= e);

  return (
    <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
      {/* 좌: 66권 */}
      <div style={{ width: 260, overflowY: "auto", borderRight: "1px solid #ddd",
                    padding: 8 }}>
        <div style={{ fontSize: 13, color: "#555", margin: "4px 0 8px" }}>
          설교 커버리지: 전체 {total}장 중 <b>{covered}장</b>
        </div>
        {[["구약", books.slice(0, 39)], ["신약", books.slice(39)]].map(([label, group]) => (
          <div key={label as string}>
            <div style={{ fontWeight: 600, fontSize: 12, color: "#888",
                          margin: "10px 4px 4px" }}>{label as string}</div>
            {(group as BibleBook[]).map(b => (
              <div key={b.num}
                   onClick={() => { setSel(b.num); setSelCh(null); }}
                   style={{ display: "flex", justifyContent: "space-between",
                            padding: "4px 8px", borderRadius: 4, cursor: "pointer",
                            background: sel === b.num ? "#eef" : undefined }}>
                <span>{b.name}</span>
                <span style={{ fontSize: 12,
                               color: b.covered_chapters ? "#2a7" : "#bbb" }}>
                  {b.covered_chapters}/{b.total_chapters}
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* 중: 장 그리드 */}
      <div style={{ width: 300, overflowY: "auto", borderRight: "1px solid #ddd",
                    padding: 12 }}>
        {!book && <div style={{ color: "#888" }}>왼쪽에서 책을 선택하세요.</div>}
        {book && <>
          <h3 style={{ margin: "4px 0 10px" }}>{book.name}</h3>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
            {book.chapters.map(c => (
              <div key={c.n} onClick={() => setSelCh(c.n)}
                   title={c.ranges.length ? `설교 ${c.sermons.length}편` : "미설교"}
                   style={{ width: 38, height: 32, display: "flex",
                            alignItems: "center", justifyContent: "center",
                            borderRadius: 4, cursor: "pointer", fontSize: 13,
                            border: selCh === c.n ? "2px solid #46a" : "1px solid #ddd",
                            background: c.ranges.length ? "#cfe8d5" : "#f7f7f7",
                            color: c.ranges.length ? "#1a5c2e" : "#999" }}>
                {c.n}
              </div>
            ))}
          </div>
        </>}
      </div>

      {/* 우: 절 단위 + 설교 목록 */}
      <div style={{ flex: 1, overflowY: "auto", padding: 12 }}>
        {!chapter && <div style={{ color: "#888" }}>장을 선택하면 절 단위 현황이 표시됩니다.</div>}
        {book && chapter && <>
          <h3 style={{ margin: "4px 0 10px" }}>{book.name} {chapter.n}장
            <span style={{ fontSize: 13, color: "#777", marginLeft: 8 }}>
              (총 {chapter.verses}절)</span></h3>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 3, marginBottom: 16 }}>
            {Array.from({ length: chapter.verses }, (_, i) => i + 1).map(v => (
              <span key={v}
                    title={isCovered(chapter, v) ? "설교로 다룸" : "미설교"}
                    style={{ width: 26, height: 22, display: "inline-flex",
                             alignItems: "center", justifyContent: "center",
                             fontSize: 11, borderRadius: 3,
                             background: isCovered(chapter, v) ? "#2a7" : "#eee",
                             color: isCovered(chapter, v) ? "#fff" : "#999" }}>
                {v}
              </span>
            ))}
          </div>
          {chapter.sermons.length > 0 && <>
            <h4 style={{ margin: "8px 0" }}>이 장을 다룬 설교 ({chapter.sermons.length}편)</h4>
            {chapter.sermons.map((s, i) => (
              <div key={i} style={{ padding: "6px 10px", marginBottom: 6,
                                    background: "#f6faf7", borderRadius: 6 }}>
                <div style={{ fontWeight: 600 }}>{s.title}</div>
                <div style={{ fontSize: 12, color: "#666" }}>{s.date} · {s.passage}</div>
              </div>
            ))}
          </>}
          {chapter.sermons.length === 0 &&
            <div style={{ color: "#888" }}>이 장을 다룬 설교가 아직 없습니다.</div>}
        </>}
      </div>
    </div>
  );
}
