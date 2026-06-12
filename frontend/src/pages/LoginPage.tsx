import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";

import { login } from "@/api/client";
import { AlertCircleIcon, BoltIcon, MailIcon } from "@/components/icons";
import { useSession } from "@/lib/session";
import "@/styles/login.css";

interface Persona {
  initials: string;
  name: string;
  email: string;
  detail: string;
  scenario: "esc" | "ok" | "deny";
  tag: string;
}

const PERSONAS: Persona[] = [
  {
    initials: "AS",
    name: "Aarav Sharma",
    email: "aarav.sharma@example.com",
    detail: "₹2,39,900 MacBook, 5 days old",
    scenario: "esc",
    tag: "ESCALATE CASE",
  },
  {
    initials: "RM",
    name: "Rohan Mehta",
    email: "rohan.mehta@example.com",
    detail: "₹699 HDMI cable, sealed",
    scenario: "ok",
    tag: "APPROVE CASE",
  },
  {
    initials: "SP",
    name: "Sneha Pillai",
    email: "sneha.pillai@example.com",
    detail: "order 45 days past delivery",
    scenario: "deny",
    tag: "DENY CASE",
  },
];

export function LoginPage() {
  const [email, setEmail] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { signIn } = useSession();
  const navigate = useNavigate();

  async function attempt(value: string) {
    const target = value.trim();
    if (!target || busy) return;
    setBusy(true);
    setError(null);
    try {
      signIn(await login(target));
      navigate("/home");
    } catch (err) {
      const notFound = err instanceof Error && err.message.includes("404");
      setError(
        notFound
          ? "No account found for that email — try one of the demo customers below."
          : "Can't reach the server right now — please try again in a moment.",
      );
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void attempt(email);
  }

  return (
    <div className="login">
      <nav>
        <div className="brand">
          <div className="mark">
            <BoltIcon />
          </div>
          <b>KaranKart</b>
        </div>
        <Link className="navnote" to="/home">
          Browse without an account →
        </Link>
      </nav>

      <div className="wrap">
        <form className="card" onSubmit={submit}>
          <div className="logo">
            <BoltIcon />
          </div>
          <p className="h">Welcome back</p>
          <p className="sub">Enter the email on your account to continue</p>
          <label htmlFor="login-email">Email address</label>
          <div className="input">
            <MailIcon />
            <input
              id="login-email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
              autoComplete="email"
            />
          </div>
          {error && <p className="err">{error}</p>}
          <button type="submit" className="cta" disabled={busy}>
            {busy ? "Checking…" : "Continue"}
          </button>
          <div className="mocknote">
            <AlertCircleIcon />
            Demo mode — no password needed. Your email selects one of 15 seeded customer profiles.
          </div>
        </form>

        <div className="demo">
          <p className="demo-label">OR PICK A DEMO CUSTOMER</p>
          {PERSONAS.map((persona) => (
            <button
              key={persona.email}
              type="button"
              className="persona"
              onClick={() => attempt(persona.email)}
              disabled={busy}
            >
              <div className="av">{persona.initials}</div>
              <div>
                <b>{persona.name}</b>
                <small>
                  {persona.email} · {persona.detail}
                </small>
              </div>
              <span className="sp" />
              <span className={`scen sc-${persona.scenario}`}>{persona.tag}</span>
            </button>
          ))}
        </div>

        <p className="verify-note">
          Identity is verified by order lookup — the same way phone support asks for your order
          number
        </p>
      </div>
    </div>
  );
}
