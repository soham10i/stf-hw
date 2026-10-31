// The consent banner: asked once, on the first visit. It explains the one cookie the site always
// needs (the signed session that keeps a visitor's orders, chats and photos their own) and asks
// whether usage may also be measured - saying exactly what services/api/visits.py stores and
// public/legal/privacy.html describes (change the three together). Accepting starts the beacon (shared/track.ts); declining
// is stored too, so the question is not asked again - and nothing is measured, either way the
// banner never returns until the choice expires.
import { useEffect, useState } from "react";
import { consent, setConsent, track, type Consent } from "../shared/track";
import { Icon } from "../shared/icons";

export function ConsentBanner({ page }: { page: string }) {
  const [ask, setAsk] = useState<Consent | "ask">(() => consent() ?? "ask");
  useEffect(() => {
    if (ask === "accepted") track(page); // a returning visitor who said yes: the page counts
  }, [ask, page]);
  if (ask !== "ask") return null;

  const answer = (c: Consent) => {
    setConsent(c);
    setAsk(c); // the effect above sends the first beacon when the state lands on "accepted"
  };

  return (
    <div className="consent-veil" role="dialog" aria-modal="false" aria-label="Cookie consent">
      <div className="consent-card">
        <div className="consent-head">
          <span className="consent-mark"><Icon name="shield" size={16} /></span>
          <b>Cookies &amp; usage</b>
        </div>
        <p>
          A signed <b>session cookie</b> is always on: it keeps your orders, chats and photos
          yours alone — nothing works without it. With your OK we also store which pages you
          open and when, your browser type, and your <b>IP address shortened</b> to its network
          (the last part set to zero), for 90 days; the site's owner gets one email per visit
          naming the page. No location lookup, no names — and nothing at all if you say no.
        </p>
        <p className="consent-links">
          <a href={`${import.meta.env.BASE_URL}legal/privacy.html`}>Privacy notice</a>
          {" · "}
          <a href={`${import.meta.env.BASE_URL}legal/imprint.html`}>Imprint</a>
        </p>
        <div className="consent-actions">
          <button className="consent-yes" onClick={() => answer("accepted")}>Accept</button>
          <button className="consent-no" onClick={() => answer("declined")}>No thanks</button>
        </div>
      </div>
    </div>
  );
}
