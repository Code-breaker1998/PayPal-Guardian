"use client";

import {
  FormEvent,
  MouseEvent,
  useEffect,
  useState,
} from "react";

const API =
  process.env.NEXT_PUBLIC_GUARDIAN_API_URL ??
  "http://localhost:8000";

const AGENT =
  process.env.NEXT_PUBLIC_DEMO_AGENT_URL ??
  "http://localhost:8100";

type Action =
  | "recommend"
  | "purchase"
  | "approval"
  | "paypal"
  | null;

type CountKey =
  | "total"
  | "allow"
  | "review"
  | "block";

type DashboardItem = {
  intent_id: string;
  merchant: string;
  domain: string;
  trust_level: string;
  amount: number;
  currency: string;
  decision: string;
  risk_score: number;
};

type Dashboard = {
  tagline: string;
  counts: Record<CountKey, number>;
  recent: DashboardItem[];
};

type Product = {
  product_id: string;
  name: string;
  merchant_name: string;
  product_url: string;
  price: number;
  rating: number;
};

type GuardianDecision = {
  intent_id: string;
  decision: "ALLOW" | "REVIEW" | "BLOCK";
  risk_score: number;
  signature_verified: boolean;
};

type AgentResult = {
  model: string;
  product: Product;
  reasoning: string[];
  interpreted_budget?: number;
  guardian?: GuardianDecision;
};

type Approval = {
  payment_intent_id: string;
  status: "PENDING" | "APPROVED" | "REJECTED";
  decided_by: string | null;
  decision_note: string | null;
  merchant: string | null;
  amount: number | null;
  currency: string | null;
  risk_score: number | null;
  reason_codes: string[];
};

type PayPalOrder = {
  payment_intent_id: string;
  paypal_order_id: string;
  status: string;
  approval_url: string | null;
  capture_id: string | null;
};

function getErrorMessage(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }

  return "Request failed";
}

async function readResponseBody(
  response: Response,
): Promise<any> {
  const contentType =
    response.headers.get("content-type") ?? "";

  if (contentType.includes("application/json")) {
    return response.json();
  }

  return response.text();
}

export default function Home() {
  const [dashboard, setDashboard] =
    useState<Dashboard | null>(null);

  const [approvals, setApprovals] =
    useState<Approval[]>([]);

  const [prompt, setPrompt] = useState(
    "Buy me the best wireless keyboard under $100",
  );

  const [result, setResult] =
    useState<AgentResult | null>(null);

  const [error, setError] = useState("");

  const [activeAction, setActiveAction] =
    useState<Action>(null);

  async function loadDashboard(): Promise<void> {
    const response = await fetch(
      `${API}/api/v1/dashboard`,
      { cache: "no-store" },
    );

    if (!response.ok) {
      throw new Error(
        "Guardian dashboard unavailable",
      );
    }

    setDashboard(await response.json());
  }

  async function loadApprovals(): Promise<void> {
    const response = await fetch(
      `${API}/api/v1/approvals`,
      { cache: "no-store" },
    );

    if (!response.ok) {
      throw new Error(
        "Approval queue unavailable",
      );
    }

    setApprovals(await response.json());
  }

  async function refresh(): Promise<void> {
    await Promise.all([
      loadDashboard(),
      loadApprovals(),
    ]);
  }

  useEffect(() => {
    void refresh().catch((caughtError) => {
      setError(getErrorMessage(caughtError));
    });
  }, []);

  async function runAgent(
    event:
      | FormEvent<HTMLFormElement>
      | MouseEvent<HTMLButtonElement>,
    action: "recommend" | "purchase",
  ): Promise<void> {
    event.preventDefault();
    event.stopPropagation();

    setActiveAction(action);
    setError("");

    try {
      const endpoint =
        action === "purchase"
          ? "/agent/purchase"
          : "/agent/recommend";

      const response = await fetch(
        `${AGENT}${endpoint}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ prompt }),
        },
      );

      const body = await readResponseBody(
        response,
      );

      if (!response.ok) {
        const detail =
          typeof body === "object"
            ? body.detail ?? body
            : body;

        throw new Error(
          typeof detail === "string"
            ? detail
            : JSON.stringify(detail),
        );
      }

      setResult(body as AgentResult);

      if (action === "purchase") {
        await refresh();
      }
    } catch (caughtError) {
      setError(getErrorMessage(caughtError));
    } finally {
      setActiveAction(null);
    }
  }

  async function decideApproval(
    intentId: string,
    decision: "approve" | "reject",
  ): Promise<void> {
    setActiveAction("approval");
    setError("");

    try {
      const response = await fetch(
        `${API}/api/v1/payment-intents/${intentId}/${decision}`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            decided_by: "hackathon-admin",
            note:
              decision === "approve"
                ? "Approved for payment"
                : "Rejected by user",
          }),
        },
      );

      const body = await readResponseBody(
        response,
      );

      if (!response.ok) {
        const detail =
          typeof body === "object"
            ? body.detail ?? body
            : body;

        throw new Error(
          typeof detail === "string"
            ? detail
            : JSON.stringify(detail),
        );
      }

      await refresh();
    } catch (caughtError) {
      setError(getErrorMessage(caughtError));
    } finally {
      setActiveAction(null);
    }
  }

  async function createPayPalOrder(
    intentId: string,
  ): Promise<void> {
    setActiveAction("paypal");
    setError("");

    try {
      const response = await fetch(
        `${API}/api/v1/payment-intents/${intentId}/paypal-order`,
        { method: "POST" },
      );

      const body = await readResponseBody(
        response,
      );

      if (!response.ok) {
        const detail =
          typeof body === "object"
            ? body.detail ?? body
            : body;

        throw new Error(
          typeof detail === "string"
            ? detail
            : JSON.stringify(detail),
        );
      }

      const order = body as PayPalOrder;

      if (!order.approval_url) {
        throw new Error(
          "PayPal approval URL was not returned",
        );
      }

      window.location.assign(
        order.approval_url,
      );
    } catch (caughtError) {
      setError(getErrorMessage(caughtError));
      setActiveAction(null);
    }
  }

  const countKeys: CountKey[] = [
    "total",
    "allow",
    "review",
    "block",
  ];

  return (
    <main>
      <header>
        <div>
          <p className="eyebrow">
            PHASE 6 · HUMAN APPROVAL + PAYPAL
          </p>

          <h1>PayPal Guardian</h1>

          <p>
            Self-hosted AI, Guardian merchant
            verification, human approval, and PayPal
            Sandbox.
          </p>
        </div>

        <span className="status">
          ● Local
        </span>
      </header>

      {error && (
        <div className="error">
          {error}
        </div>
      )}

      <section className="cards">
        {countKeys.map((key) => (
          <article
            key={key}
            className={key}
          >
            <small>
              {key.toUpperCase()}
            </small>

            <strong>
              {dashboard?.counts?.[key] ?? 0}
            </strong>
          </article>
        ))}
      </section>

      <form
        className="panel"
        onSubmit={(event) =>
          void runAgent(event, "recommend")
        }
      >
        <h2>Shopping request</h2>

        <textarea
          value={prompt}
          onChange={(event) =>
            setPrompt(event.target.value)
          }
          minLength={8}
          maxLength={500}
          required
        />

        <div className="actions">
          <button
            type="submit"
            disabled={activeAction !== null}
          >
            {activeAction === "recommend"
              ? "Getting recommendation..."
              : "Get recommendation"}
          </button>

          <button
            type="button"
            className="gold"
            disabled={activeAction !== null}
            onClick={(event) =>
              void runAgent(event, "purchase")
            }
          >
            {activeAction === "purchase"
              ? "Signing and sending..."
              : "Recommend + signed intent"}
          </button>
        </div>
      </form>

      {result && (
        <section className="panel result">
          <div>
            <h2>{result.product.name}</h2>

            <p>
              {result.product.merchant_name} · ${
                result.product.price.toFixed(2)
              } · Rating {result.product.rating}
            </p>

            <p className="mono">
              {result.product.product_url}
            </p>
          </div>

          <div>
            <h3>AI reasoning</h3>

            <ul>
              {result.reasoning.map(
                (reason, index) => (
                  <li key={`${index}-${reason}`}>
                    {reason}
                  </li>
                ),
              )}
            </ul>

            {result.guardian && (
              <div
                className={`decision ${result.guardian.decision.toLowerCase()}`}
              >
                <b>
                  GUARDIAN {result.guardian.decision}
                </b>

                <span>
                  Risk {result.guardian.risk_score} ·
                  Signature{" "}
                  {result.guardian.signature_verified
                    ? "verified"
                    : "failed"}
                </span>
              </div>
            )}
          </div>
        </section>
      )}

      <section className="panel">
        <h2>Human approval queue</h2>

        {approvals.length === 0 && (
          <p>No approvals found.</p>
        )}

        {approvals.map((approval) => (
          <div
            className="row"
            key={approval.payment_intent_id}
          >
            <div>
              <b>
                {approval.merchant ??
                  approval.payment_intent_id}
              </b>

              <small>
                {approval.payment_intent_id} ·{" "}
                {approval.status}
              </small>
            </div>

            <span>
              {approval.amount == null
                ? "-"
                : `${approval.currency ?? "USD"} ${approval.amount.toFixed(2)}`}
            </span>

            <span>
              Risk {approval.risk_score ?? "-"}
            </span>

            <div className="actions">
              {approval.status === "PENDING" && (
                <>
                  <button
                    type="button"
                    disabled={
                      activeAction !== null
                    }
                    onClick={() =>
                      void decideApproval(
                        approval.payment_intent_id,
                        "approve",
                      )
                    }
                  >
                    Approve
                  </button>

                  <button
                    type="button"
                    disabled={
                      activeAction !== null
                    }
                    onClick={() =>
                      void decideApproval(
                        approval.payment_intent_id,
                        "reject",
                      )
                    }
                  >
                    Reject
                  </button>
                </>
              )}

              {approval.status === "APPROVED" && (
                <button
                  type="button"
                  className="gold"
                  disabled={activeAction !== null}
                  onClick={() =>
                    void createPayPalOrder(
                      approval.payment_intent_id,
                    )
                  }
                >
                  {activeAction === "paypal"
                    ? "Creating PayPal order..."
                    : "Continue to PayPal"}
                </button>
              )}
            </div>
          </div>
        ))}
      </section>

      <section className="panel">
        <h2>Recent Guardian decisions</h2>

        {dashboard?.recent?.map((row) => (
          <div
            className="row"
            key={row.intent_id}
          >
            <div>
              <b>{row.merchant}</b>

              <small>
                {row.domain} · {row.trust_level}
              </small>
            </div>

            <span>
              {row.currency} {row.amount.toFixed(2)}
            </span>

            <span
              className={`badge ${row.decision.toLowerCase()}`}
            >
              {row.decision}
            </span>

            <span>
              Risk {row.risk_score}
            </span>
          </div>
        ))}
      </section>
    </main>
  );
}
