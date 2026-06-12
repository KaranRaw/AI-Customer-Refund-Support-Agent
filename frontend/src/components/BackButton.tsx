import { useLocation, useNavigate } from "react-router-dom";

import { ArrowLeftIcon } from "@/components/icons";

// Where "back" goes when there is no in-app history to pop (e.g. the page was opened
// directly in a fresh tab). Keeps the user inside the app instead of leaving it.
const FALLBACK: Record<string, string> = {
  "/orders": "/home",
  "/chat": "/home",
  "/voice": "/chat",
};

export function BackButton() {
  const navigate = useNavigate();
  const { pathname, key } = useLocation();

  // Login ("/") and home are roots — there is nothing to go back to.
  if (pathname === "/" || pathname === "/home") return null;

  function goBack() {
    // key === "default" means this is the first entry in the history stack, so
    // navigate(-1) would exit the app — fall back to a sensible in-app destination.
    if (key !== "default") navigate(-1);
    else navigate(FALLBACK[pathname] ?? "/home");
  }

  return (
    <div className="backbar">
      <button type="button" className="backbtn" onClick={goBack} aria-label="Go back">
        <ArrowLeftIcon />
        Back
      </button>
    </div>
  );
}
