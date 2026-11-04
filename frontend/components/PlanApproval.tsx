import type { ReviewSummary } from "@/lib/types";

/** "Approve plan": decision support, a person approves. Disabled while a severity 4-5 entry is still pending. */
export function PlanApproval({ review, busy, onApprove }: { review: ReviewSummary; busy: boolean; onApprove: () => void }) {
  const blocked = review.blocking.length > 0;
  const excluded = review.rejected_excluded.length;
  const waiting = review.rejected_pending_replan.length;
  return (
    <div className="plan-approval">
      <div className="row">
        {review.plan_approval ? (
          <span className="badge ok">Approved by reviewer at {new Date(review.plan_approval.at).toLocaleString()}</span>
        ) : (
          <button onClick={onApprove} disabled={busy || blocked}>
            Approve plan
          </button>
        )}
        <span className="muted small">
          {review.plan_approval
            ? "A person approved this plan. Walkdown is decision support; it issues no work."
            : blocked
              ? `Review the severity 4-5 entries first: ${review.blocking.join(", ")} still pending.`
              : "Decision support: the plan takes effect only when a person approves it. A replan or a new review decision withdraws the approval."}
        </span>
      </div>
      {(excluded > 0 || waiting > 0) && (
        <div className="muted small" style={{ marginTop: 6 }}>
          {excluded > 0 && `${excluded} rejected, excluded from plan. `}
          {waiting > 0 && `${waiting} rejected since the last plan: replan (Something changed on site?) to take ${waiting === 1 ? "it" : "them"} out.`}
        </div>
      )}
    </div>
  );
}
