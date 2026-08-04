import type {
  TheologyReviewClaim,
  TheologyReviewDocument,
  TheologyReviewStatus,
} from "./theologyReviewTypes";

const OPTIONS: { value: TheologyReviewStatus; label: string }[] = [
  { value: "historical_verified", label: "과거 확인" },
  { value: "approved", label: "승인" },
  { value: "needs_edit", label: "수정 필요" },
  { value: "deferred", label: "보류" },
  { value: "rejected", label: "제외" },
];

const DOMAIN_LABELS: Record<string, string> = {
  soteriology: "구원론",
  sanctification: "성화",
  theological_anthropology: "인간론",
  eschatology: "종말론",
  ecclesiology: "교회론",
  hermeneutics: "해석 원리",
  christology: "기독론",
  discipleship: "제자도",
  general_discipleship: "일반 제자도",
  theology_proper: "하나님론",
  scripture: "성경관",
  pastoral_care: "목회·돌봄",
  mission: "선교·전도",
  pneumatology: "성령론",
  sermon_structure: "설교 구조",
};

const STATUS_LABELS: Record<TheologyReviewStatus, string> = {
  pending: "미검토",
  historical_verified: "과거 설교 확인",
  approved: "승인 권고",
  needs_edit: "수정 권고",
  deferred: "보류 권고",
  rejected: "제외 권고",
};

export default function TheologyReview({
  value,
  onChange,
}: {
  value: TheologyReviewDocument;
  onChange: (next: TheologyReviewDocument) => void;
}) {
  const decided = value.claims.filter(claim => claim.status !== "pending").length;
  const historicalMode = value.review_mode === "historical";

  function updateClaim(id: string, patch: Partial<TheologyReviewClaim>) {
    onChange({
      ...value,
      claims: value.claims.map(claim =>
        claim.id === id ? { ...claim, ...patch } : claim),
    });
  }

  function applyRecommendations() {
    onChange({
      ...value,
      claims: value.claims.map(claim =>
        claim.status === "pending" && claim.recommendation
          ? { ...claim, status: claim.recommendation }
          : claim),
    });
  }

  return (
    <section className="theology-review">
      <div className="theology-review-summary">
        <div>
          <span>{historicalMode ? "과거 설교 원문 확인" : "목사님 신학 프로필 승인 후보"}</span>
          <strong>{value.title}</strong>
          {value.corpus && <small>{value.corpus}</small>}
        </div>
        <b>{decided} / {value.claims.length} 검토</b>
        {value.claims.some(claim => claim.status === "pending" && claim.recommendation) && (
          <button type="button" onClick={applyRecommendations}>
            {historicalMode ? "과거 설교 일괄 확인" : "권고 판정 일괄 선택"}
          </button>
        )}
      </div>
      <div className="theology-review-progress" aria-label="검토 진행률">
        <i style={{ width: `${value.claims.length ? decided / value.claims.length * 100 : 0}%` }} />
      </div>
      <div className="theology-review-list">
        {value.claims.map(claim => (
          <article className={`theology-review-card status-${claim.status}`} key={claim.id}>
            <header>
              <span>{DOMAIN_LABELS[claim.domain] || claim.domain}</span>
              <code>{claim.id}</code>
              {claim.confidence && <small>근거 신뢰도 {claim.confidence}</small>}
            </header>
            <p>{claim.claim}</p>
            {claim.review_reason && (
              <div className="theology-review-reason">
                <strong>확인할 점</strong>
                {claim.review_reason}
              </div>
            )}
            {claim.recommendation && claim.cross_check && (
              <div className={`theology-review-crosscheck recommend-${claim.recommendation}`}>
                <div>
                  <strong>전체 설교 교차검증</strong>
                  <b>{STATUS_LABELS[claim.recommendation]}</b>
                </div>
                <p>{claim.cross_check}</p>
                {!!claim.related_sermons?.length && (
                  <details>
                    <summary>대표 관련 설교 {claim.related_sermons.length}편</summary>
                    <ul>
                      {claim.related_sermons.map(source => <li key={source}>{source}</li>)}
                    </ul>
                  </details>
                )}
                {claim.status === "pending" && (
                  <button type="button"
                          onClick={() => updateClaim(
                            claim.id, { status: claim.recommendation })}>
                    권고 판정 선택
                  </button>
                )}
              </div>
            )}
            {!!claim.evidence?.length && (
              <details>
                <summary>근거 {claim.evidence.length}개</summary>
                <ul>
                  {claim.evidence.map(source => <li key={source}>{source}</li>)}
                </ul>
              </details>
            )}
            <div className="theology-review-options" role="group"
                 aria-label={`${claim.id} 승인 상태`}>
              {OPTIONS.map(option => (
                <button key={option.value} type="button"
                        className={claim.status === option.value ? "selected" : ""}
                        onClick={() => updateClaim(claim.id, { status: option.value })}>
                  {option.label}
                </button>
              ))}
            </div>
            <label>
              <span>목사님 의견</span>
              <textarea value={claim.review_note || ""}
                        onChange={event => updateClaim(
                          claim.id, { review_note: event.target.value })}
                        placeholder="수정할 표현이나 판단 근거를 적어주세요." />
            </label>
          </article>
        ))}
      </div>
    </section>
  );
}
