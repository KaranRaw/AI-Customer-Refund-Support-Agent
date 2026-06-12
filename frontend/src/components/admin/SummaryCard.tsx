import { RefreshIcon, SparkleIcon } from "@/components/icons";
import type { CaseFact } from "@/types";

interface Props {
  summary: string | null;
  facts: CaseFact[];
  generatedAt: string | null;
  stepCount: number;
  model: string;
  generating: boolean;
  onGenerate: () => void;
}

function clock(iso: string | null): string {
  if (!iso) return "";
  return new Date(iso).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" });
}

export function SummaryCard({
  summary,
  facts,
  generatedAt,
  stepCount,
  model,
  generating,
  onGenerate,
}: Props) {
  // State 2 — generating.
  if (generating) {
    return (
      <div className="dcard">
        <div className="sum-head">
          <div className="sum-spark">
            <SparkleIcon />
          </div>
          <b>Case summary</b>
        </div>
        <div className="sum-skel">
          <div className="sum-sk" />
          <div className="sum-sk" />
          <div className="sum-sk" />
        </div>
        <p className="sum-skl">
          <span className="sum-dot" />
          Reading {stepCount} steps and the policy result…
        </p>
      </div>
    );
  }

  // State 1 — not yet generated.
  if (!summary) {
    return (
      <div className="dcard">
        <button type="button" className="sum-btn" onClick={onGenerate}>
          <SparkleIcon />
          Summarize this case with AI
        </button>
      </div>
    );
  }

  // State 3 — summary ready.
  return (
    <div className="dcard">
      <div className="sum-head">
        <div className="sum-spark">
          <SparkleIcon />
        </div>
        <b>Case summary</b>
        <button type="button" className="sum-regen" onClick={onGenerate} aria-label="Regenerate summary">
          <RefreshIcon />
        </button>
      </div>
      <p className="sum-text">{summary}</p>
      {facts.length > 0 && (
        <div className="sum-facts">
          {facts.map((fact) => (
            <span key={fact.label} className={`sum-chip${fact.tone === "warn" ? " warn" : ""}`}>
              {fact.label}
            </span>
          ))}
        </div>
      )}
      <p className="sum-meta">
        <span>
          Generated from {stepCount} steps · {model}
        </span>
        <span>{clock(generatedAt)}</span>
      </p>
    </div>
  );
}
