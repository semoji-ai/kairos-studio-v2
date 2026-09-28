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

  if (error) return <div className="page-status">⚠️ {error}</div>;
  if (!books) return <div className="page-status">커버리지 계산 중…</div>;

  const total = books.reduce((a, b) => a + b.total_chapters, 0);
  const covered = books.reduce((a, b) => a + b.covered_chapters, 0);

  const isCovered = (c: BibleChapter, v: number) =>
    c.ranges.some(([s, e]) => v >= s && v <= e);

  return (
    <div className="coverage">
      {/* 좌: 66권 */}
      <div className="coverage-pane coverage-books">
        <div className="coverage-summary">
          설교 커버리지<br />전체 {total}장 중 <b>{covered}장</b>
        </div>
        {[["구약", books.slice(0, 39)], ["신약", books.slice(39)]].map(([label, group]) => (
          <div key={label as string}>
            <div className="coverage-group">{label as string}</div>
            {(group as BibleBook[]).map(b => (
              <div key={b.num}
                   onClick={() => { setSel(b.num); setSelCh(null); }}
                   className={`book-item${sel === b.num ? " is-active" : ""}`}>
                <span>{b.name}</span>
                <span className={`book-count${b.covered_chapters ? " has" : ""}`}>
                  {b.covered_chapters}/{b.total_chapters}
                </span>
              </div>
            ))}
          </div>
        ))}
      </div>

      {/* 중: 장 그리드 */}
      <div className="coverage-pane coverage-chapters">
        {!book && <div className="empty-hint">왼쪽에서 책을 선택하세요.</div>}
        {book && <>
          <h3>{book.name}</h3>
          <div className="chapter-grid">
            {book.chapters.map(c => (
              <div key={c.n} onClick={() => setSelCh(c.n)}
                   title={c.ranges.length ? `설교 ${c.sermons.length}편` : "미설교"}
                   className={`chapter-cell${c.ranges.length ? " covered" : ""}${selCh === c.n ? " is-selected" : ""}`}>
                {c.n}
              </div>
            ))}
          </div>
        </>}
      </div>

      {/* 우: 절 단위 + 설교 목록 */}
      <div className="coverage-pane coverage-detail">
        {!chapter && <div className="empty-hint">장을 선택하면 절 단위 현황이 표시됩니다.</div>}
        {book && chapter && <>
          <h3>{book.name} {chapter.n}장
            <small>(총 {chapter.verses}절)</small></h3>
          <div className="verse-grid">
            {Array.from({ length: chapter.verses }, (_, i) => i + 1).map(v => (
              <span key={v}
                    title={isCovered(chapter, v) ? "설교로 다룸" : "미설교"}
                    className={`verse-cell${isCovered(chapter, v) ? " covered" : ""}`}>
                {v}
              </span>
            ))}
          </div>
          {chapter.sermons.length > 0 && <>
            <h4>이 장을 다룬 설교 ({chapter.sermons.length}편)</h4>
            {chapter.sermons.map((s, i) => (
              <div key={i} className="sermon-item">
                <strong>{s.title}</strong>
                <small>{s.date} · {s.passage}</small>
              </div>
            ))}
          </>}
          {chapter.sermons.length === 0 &&
            <div className="empty-hint">이 장을 다룬 설교가 아직 없습니다.</div>}
        </>}
      </div>
    </div>
  );
}
