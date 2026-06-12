import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import {
  AlertCircleIcon,
  BoltIcon,
  CheckIcon,
  ChevronIcon,
  SearchIcon,
  XIcon,
} from "@/components/icons";
import {
  VBADGE,
  VCLASS,
  VLABEL,
  deriveFlags,
  deriveReason,
  deriveRunStats,
  deriveTrace,
  formatClock,
  formatInr,
  formatMs,
  initials,
  mergeSteps,
} from "@/lib/adminTrace";
import { generateCaseSummary, getCase, getCases, resolveEscalation } from "@/api/client";
import { SummaryCard } from "@/components/admin/SummaryCard";
import type { CaseDetail, CaseSummary, Verdict } from "@/types";
import { useSSE } from "@/hooks/useSSE";
import "@/styles/admin.css";

function VerdictIcon({ verdict }: { verdict: Verdict }) {
  if (verdict === "approve") return <CheckIcon />;
  if (verdict === "deny") return <XIcon />;
  return <AlertCircleIcon />;
}

function caseSummaryLine(c: CaseSummary): string {
  if (!c.order_id) return "Refund inquiry";
  const price = c.order_amount != null ? ` · ${formatInr(c.order_amount)}` : "";
  const product = c.order_product ? ` · ${c.order_product}` : "";
  return `${c.order_id}${price}${product}`;
}

function caseHeadSub(detail: CaseDetail): ReactNode {
  const channel = detail.channel === "voice" ? "voice" : "text";
  if (!detail.order) return `${channel} channel`;
  return (
    <>
      <code>{detail.order.id}</code> · {detail.order.product_name} · {formatInr(detail.order.amount)} ·{" "}
      {channel} channel
    </>
  );
}

export function AdminPage() {
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<CaseDetail | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [summarizing, setSummarizing] = useState(false);
  const { events, connected } = useSSE();

  async function loadCases() {
    const list = await getCases();
    setCases(list);
    setSelectedId((current) => current ?? list[0]?.conversation_id ?? null);
  }

  // Mock manager action: approve (issues the refund) or deny an open escalation.
  async function handleResolve(decision: "approve" | "deny") {
    if (!detail?.escalation || selectedId == null) return;
    await resolveEscalation(detail.escalation.id, decision);
    getCase(selectedId).then(setDetail).catch(() => undefined);
    loadCases().catch(() => undefined);
  }

  // On-demand AI summary of the selected case (also used to regenerate).
  async function handleSummarize() {
    if (selectedId == null) return;
    setSummarizing(true);
    try {
      const result = await generateCaseSummary(selectedId);
      setDetail((prev) =>
        prev
          ? { ...prev, ai_summary: result.summary, ai_summary_at: result.generated_at }
          : prev,
      );
    } catch {
      // leave the card in its prior state; the button stays available to retry
    } finally {
      setSummarizing(false);
    }
  }

  useEffect(() => {
    loadCases().catch(() => undefined);
  }, []);

  useEffect(() => {
    setSummarizing(false); // a different case is selected — drop any in-flight summary state
    if (selectedId == null) {
      setDetail(null);
      return;
    }
    getCase(selectedId)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [selectedId]);

  // A new conversation appearing in the stream means a fresh case — refresh the list.
  useEffect(() => {
    if (events.length === 0) return;
    const last = events[events.length - 1];
    const known = new Set(cases.map((c) => c.conversation_id));
    // Refresh on a new conversation, and again when its run finishes (decision step).
    if (!known.has(last.conversation_id) || last.type === "decision") {
      loadCases().catch(() => undefined);
    }
  }, [events]);

  const liveSteps = useMemo(() => {
    if (!detail) return [];
    const live = events.filter((e) => e.conversation_id === selectedId);
    return mergeSteps(detail.steps, live);
  }, [detail, events, selectedId]);

  const streamingIds = useMemo(() => new Set(events.map((e) => e.conversation_id)), [events]);
  const trace = useMemo(() => deriveTrace(liveSteps), [liveSteps]);

  const live = detail ? { ...detail, steps: liveSteps } : null;
  const verdict = detail?.verdict ?? null;
  const reason = live ? deriveReason(live) : "";
  const runStats = live ? deriveRunStats(live) : null;
  const flags = live ? deriveFlags(live) : [];
  const totalMs = liveSteps.reduce((sum, s) => sum + (s.latency_ms ?? 0), 0);

  function toggleStep(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  return (
    <div className="admin">
      <nav>
        <div className="brand">
          <div className="mark">
            <BoltIcon />
          </div>
          <b>KaranKart</b>
          <span className="crumb">
            <i>/</i>Admin · Reasoning logs
          </span>
        </div>
        <div className="tools">
          <Link to="/chat" className="tbtn">
            ← Chat
          </Link>
          <span className="tbtn">Policy 30d · ₹50k</span>
          <span className={`live${connected ? "" : " off"}`}>
            <i />
            {connected ? "Live · SSE connected" : "Reconnecting…"}
          </span>
        </div>
      </nav>

      <div className="app">
        <aside className="side">
          <div className="search">
            <SearchIcon />
            <input placeholder="Search cases…" readOnly />
          </div>
          <div className="side-head">
            <b>REFUND CASES</b>
            <span className="count">{cases.length} TOTAL</span>
          </div>
          <div className="cases">
            {cases.length === 0 && <div className="empty">No cases yet — start a chat.</div>}
            {cases.map((c) => (
              <button
                key={c.conversation_id}
                type="button"
                className={`case${c.conversation_id === selectedId ? " active" : ""}`}
                onClick={() => setSelectedId(c.conversation_id)}
              >
                <div className="av">{initials(c.customer_name)}</div>
                <div className="cb">
                  <div className="cr1">
                    <b>{c.customer_name ?? "Unknown"}</b>
                    <time>{formatClock(c.created_at)}</time>
                  </div>
                  <p className="cr2">{caseSummaryLine(c)}</p>
                  {c.verdict && <span className={`badge ${VBADGE[c.verdict]}`}>{VLABEL[c.verdict]}</span>}
                  {streamingIds.has(c.conversation_id) && (
                    <>
                      {" "}
                      <span className="badge b-live">STREAMING</span>
                    </>
                  )}
                </div>
              </button>
            ))}
          </div>
        </aside>

        <main className="main">
          {detail ? (
            <>
              <div className="case-head">
                <div className="who">
                  <b>
                    {detail.customer?.name ?? "Case"} — Case RR-{detail.conversation_id}
                  </b>
                  <span>{caseHeadSub(detail)}</span>
                </div>
                <div className="spacer" />
                <span className="mchip">{liveSteps.length} STEPS</span>
                {verdict && <span className={`vchip ${VCLASS[verdict]}`}>VERDICT · {VLABEL[verdict]}</span>}
              </div>

              <div className="trace">
                <p className="tlabel">
                  <i />
                  EXECUTION TRACE{connected ? " — STREAMING" : ""}
                </p>
                <div className="tl">
                  {trace.map((row) => (
                    <div
                      key={row.key}
                      className={`node${row.kind === "llm" ? " llm" : ""}${row.kind === "warn" ? " warn" : ""}`}
                    >
                      <span className="pin">
                        <i />
                      </span>
                      <div className="step" onClick={() => toggleStep(row.key)}>
                        <span className="tm">{row.time}</span>
                        <span className="nm">{row.name}</span>
                        <span className="dt">{row.desc}</span>
                        <span className="tag">{row.tag}</span>
                        <span className="ms">{row.ms}</span>
                        <span className={`caret${expanded.has(row.key) ? " open" : ""}`}>
                          <ChevronIcon />
                        </span>
                      </div>
                      {row.checks && (
                        <div className="tree">
                          {row.checks.map((check) => (
                            <div key={check.name} className={`tr ${check.pass ? "pass" : "fail"}`}>
                              <span className="tk">{check.pass ? <CheckIcon /> : <XIcon />}</span>
                              {check.name}
                              <span className="why">{check.why}</span>
                            </div>
                          ))}
                        </div>
                      )}
                      {expanded.has(row.key) && row.raw && (
                        <div className="payload">
                          {row.raw.input != null && (
                            <div className="pl-block">
                              <span className="pl-label">input</span>
                              <pre>{JSON.stringify(row.raw.input, null, 2)}</pre>
                            </div>
                          )}
                          {row.raw.output != null && (
                            <div className="pl-block">
                              <span className="pl-label">output</span>
                              <pre>{JSON.stringify(row.raw.output, null, 2)}</pre>
                            </div>
                          )}
                          {row.raw.input == null && row.raw.output == null && (
                            <div className="pl-empty">No payload recorded for this step.</div>
                          )}
                        </div>
                      )}
                    </div>
                  ))}

                  {verdict && (
                    <div className="node final">
                      <span className="pin">
                        <i />
                      </span>
                      <div className={`verdict ${VCLASS[verdict]}`}>
                        <div className="vk">
                          <VerdictIcon verdict={verdict} />
                        </div>
                        <div>
                          <b>VERDICT · {VLABEL[verdict]}</b>
                          <span>{reason}</span>
                        </div>
                        {totalMs > 0 && <span className="ms">TOTAL {formatMs(totalMs)}</span>}
                      </div>
                    </div>
                  )}
                </div>
                {verdict && verdict !== "approve" && (
                  <p className="foot-note">
                    <code>issue_refund()</code> was never called — a refund cannot execute on a
                    non-APPROVE verdict (defense-in-depth).
                  </p>
                )}
              </div>
            </>
          ) : (
            <div className="empty">Select a case to see its reasoning trace.</div>
          )}
        </main>

        <aside className="detail">
          <p className="dlabel">CASE DETAILS</p>

          {detail && (
            <SummaryCard
              summary={detail.ai_summary}
              facts={detail.summary_facts}
              generatedAt={detail.ai_summary_at}
              stepCount={liveSteps.length}
              model={runStats?.model ?? "gpt-4.1-mini"}
              generating={summarizing}
              onGenerate={handleSummarize}
            />
          )}

          {detail?.customer && (
            <div className="dcard">
              <div className="dhead">
                <div className="av">{initials(detail.customer.name)}</div>
                <div>
                  <b>{detail.customer.name}</b>
                  <small>{detail.customer.email}</small>
                </div>
                {detail.customer.tier && <span className="tierpill">{detail.customer.tier}</span>}
              </div>
              <div className="row">
                <span>Customer ID</span>
                <b>
                  <code>{detail.customer.id}</code>
                </b>
              </div>
              <div className="row">
                <span>Channel</span>
                <b>{detail.channel === "voice" ? "Voice" : "Text chat"}</b>
              </div>
            </div>
          )}

          {detail?.order && (
            <div className="dcard">
              <div className="row">
                <span>Order</span>
                <b>
                  <code>{detail.order.id}</code>
                </b>
              </div>
              <div className="row">
                <span>Product</span>
                <b>{detail.order.product_name}</b>
              </div>
              <div className="row">
                <span>Amount</span>
                <b>{formatInr(detail.order.amount)}</b>
              </div>
              {detail.order.delivered_at && (
                <div className="row">
                  <span>Delivered</span>
                  <b>
                    {new Date(detail.order.delivered_at).toLocaleDateString("en-US", {
                      month: "short",
                      day: "numeric",
                    })}
                  </b>
                </div>
              )}
              {detail.refund_reason && (
                <div className="row">
                  <span>Refund reason</span>
                  <b>{detail.refund_reason}</b>
                </div>
              )}
              <div className="flags">
                {flags.map((flag) => (
                  <span key={flag.label} className={`flag ${flag.kind}`}>
                    {flag.label}
                  </span>
                ))}
              </div>
            </div>
          )}

          {detail?.escalation && (
            <div className="dcard ticket-card">
              <div className="row">
                <span>Escalation</span>
                <b>
                  <code>#{detail.escalation.ref}</code>
                </b>
              </div>
              <div className="row">
                <span>Assigned to</span>
                <b>{detail.escalation.assigned_to}</b>
              </div>
              <div className="row">
                <span>Reason</span>
                <b>{detail.escalation.reason}</b>
              </div>
              <div className="row">
                <span>Status</span>
                <span className="openpill">{detail.escalation.status.toUpperCase()}</span>
              </div>
              {detail.escalation.status === "open" && (
                <div className="resolve">
                  <button type="button" className="rbtn ok" onClick={() => handleResolve("approve")}>
                    Approve refund
                  </button>
                  <button type="button" className="rbtn no" onClick={() => handleResolve("deny")}>
                    Deny
                  </button>
                </div>
              )}
            </div>
          )}

          {runStats && detail && (
            <div className="dcard">
              <div className="row">
                <span>Model</span>
                <b>
                  <code>{runStats.model}</code>
                </b>
              </div>
              <div className="row">
                <span>Tokens in / out</span>
                <b>{runStats.tokens}</b>
              </div>
              <div className="row">
                <span>Steps used</span>
                <b>{runStats.steps}</b>
              </div>
              <div className="row">
                <span>Policy</span>
                <b>30d · ₹50k</b>
              </div>
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
