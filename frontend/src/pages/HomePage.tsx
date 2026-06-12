import { Link } from "react-router-dom";

import {
  BoltIcon,
  BotIcon,
  ChatBubbleIcon,
  CheckCircleIcon,
  CheckIcon,
  ShieldCheckIcon,
} from "@/components/icons";
import { useSession } from "@/lib/session";
import "@/styles/home.css";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

export function HomePage() {
  const { customer } = useSession();

  return (
    <div className="home">
      <nav>
        <div className="brand">
          <div className="mark">
            <BoltIcon />
          </div>
          <b>KaranKart</b>
        </div>
        <div className="links">
          <Link to="/orders">Orders</Link>
          <Link to="/chat">Support</Link>
          {customer ? (
            <div className="me" title={customer.name}>
              {initials(customer.name)}
            </div>
          ) : (
            <Link to="/">Sign in</Link>
          )}
        </div>
      </nav>

      <div className="hero">
        <div className="hero-inner">
          <div>
            <span className="pill">
              <i />
              AI support online · avg resolution 54s
            </span>
            <h1>
              Refunds decided in seconds — <em>with reasoning you can see.</em>
            </h1>
            <p className="sub">
              Our AI assistant finds your order, checks your request against the return policy, and
              decides on the spot — and explains the policy reason behind every decision.
            </p>
            <div className="ctas">
              <Link to="/chat" className="btn w">
                <ChatBubbleIcon />
                Get support
              </Link>
              <Link to="/orders" className="btn g">
                Your orders
              </Link>
            </div>
            <div className="ticks">
              <span>
                <CheckIcon />
                30-day returns
              </span>
              <span>
                <CheckIcon />
                Defects always covered
              </span>
              <span>
                <CheckIcon />
                No hold music
              </span>
            </div>
          </div>

          <div className="stack">
            <div className="trace">
              <p className="tt">
                <i />
                AGENT REASONING — LIVE
              </p>
              <div className="trow">
                <b>lookup_customer</b>
                <span className="ok">✓</span>
                <span>cust-7 · 3 orders</span>
                <span className="ms">38ms</span>
              </div>
              <div className="trow">
                <b>get_order</b>
                <span className="ok">✓</span>
                <span>ORD-38 · ₹24,990</span>
                <span className="ms">41ms</span>
              </div>
              <div className="trow">
                <b>check_eligibility</b>
                <span className="ok">✓</span>
                <span>defective → covered</span>
                <span className="ms">12ms</span>
              </div>
              <div className="trow">
                <b>issue_refund</b>
                <span className="ok">✓</span>
                <span>re-validated · issued</span>
                <span className="ms">29ms</span>
              </div>
            </div>

            <div className="hero-chat">
              <div className="chead">
                <div className="bot">
                  <BotIcon />
                </div>
                <div>
                  <b>Refund assistant</b>
                  <span>
                    <span className="dot" />
                    Online · replies instantly
                  </span>
                </div>
              </div>
              <div className="cmsgs">
                <div className="cu">My earbuds arrived dead. I want a refund.</div>
                <div className="ca">
                  Sorry about that! Found your order — Sony WF-1000XM5, ₹24,990, delivered 3 days
                  ago.
                </div>
                <div className="ca">
                  You're covered — defective items are always refundable.
                  <div className="cticket">
                    <CheckCircleIcon />
                    ₹24,990 refund issued · 3–5 business days
                  </div>
                </div>
              </div>
            </div>

            <div className="xray">
              <div className="xk">
                <ShieldCheckIcon />
              </div>
              <div>
                <b>Every decision audited</b>
                <small>4 checks · 4.2 seconds</small>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div className="stats">
        <div className="stats-inner">
          <div className="stat">
            <b>54s</b>
            <span>average resolution</span>
          </div>
          <div className="stat">
            <b>92%</b>
            <span>resolved without a human</span>
          </div>
          <div className="stat">
            <b>100%</b>
            <span>policy-checked decisions</span>
          </div>
          <div className="stat">
            <b>24h</b>
            <span>manager review for ₹50,000+</span>
          </div>
        </div>
      </div>

      <div className="verd">
        <p className="vlabel">THREE HONEST OUTCOMES</p>
        <p className="vh">
          An assistant that can also say <em>no</em> — and knows when to ask.
        </p>
        <div className="vgrid">
          <div className="vcard">
            <span className="vpill vp-ok">APPROVE</span>
            <b>Eligible? Refunded instantly</b>
            <p>
              Within the window, sealed or defective — your money is on its way before the chat
              ends.
            </p>
          </div>
          <div className="vcard">
            <span className="vpill vp-no">DENY</span>
            <b>Out of policy? We say so</b>
            <p>
              Past 30 days or final-sale items get a clear, honest no — with the exact policy reason.
            </p>
          </div>
          <div className="vcard">
            <span className="vpill vp-esc">ESCALATE</span>
            <b>Big amounts? A human decides</b>
            <p>
              Refunds over ₹50,000 go straight to a manager — the assistant knows the limits of its
              authority.
            </p>
          </div>
        </div>
      </div>

      <footer>
        <div className="foot-inner">
          <div className="fl">
            <div className="fmark">
              <BoltIcon />
            </div>
            KaranKart · AI-powered customer support
          </div>
          <div className="fr">
            <span>Return policy</span>
            <span>Help center</span>
            <span>Contact</span>
          </div>
        </div>
      </footer>
    </div>
  );
}
