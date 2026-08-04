export type TheologyReviewStatus =
  | "pending"
  | "historical_verified"
  | "approved"
  | "needs_edit"
  | "deferred"
  | "rejected";

export type TheologyReviewClaim = {
  id: string;
  domain: string;
  claim: string;
  status: TheologyReviewStatus;
  confidence?: "high" | "medium" | "low";
  evidence?: string[];
  review_reason?: string;
  review_note?: string;
  recommendation?: Exclude<TheologyReviewStatus, "pending">;
  cross_check?: string;
  related_sermons?: string[];
};

export type TheologyReviewDocument = {
  schema: "kairos.theology-review.v1";
  title: string;
  corpus?: string;
  review_status?: "in_review" | "reviewed";
  review_mode?: "historical" | "current";
  updated_at?: string | null;
  claims: TheologyReviewClaim[];
};

export function isTheologyReview(value: unknown): value is TheologyReviewDocument {
  if (!value || typeof value !== "object") return false;
  const candidate = value as Partial<TheologyReviewDocument>;
  return candidate.schema === "kairos.theology-review.v1"
    && Array.isArray(candidate.claims);
}
