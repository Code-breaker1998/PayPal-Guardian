let evidence = null;

const productNode = document.getElementById("product");
const resultNode = document.getElementById("result");
const errorNode = document.getElementById("error");
const statusNode = document.getElementById("status");
const analyzeButton = document.getElementById("analyze");


const escapeHtml = (value) => {
  const replacements = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    "'": "&#39;",
    '"': "&quot;",
  };

  return String(value ?? "").replace(
    /[&<>'"]/g,
    (character) => replacements[character],
  );
};


function renderProduct(scan) {
  evidence = scan;

  const product = scan?.product ?? {};

  const productName =
    product.name || "No product detected";

  const productCurrency =
    product.currency || "";

  const productPrice =
    product.price ?? "-";

  const hostname =
    scan?.hostname || "";

  const extractionSource =
    product.source || "UNKNOWN";

  const confidence =
    scan?.confidence || "LOW";

  productNode.innerHTML = `
    <h2>${escapeHtml(productName)}</h2>

    <p class="price">
      ${escapeHtml(productCurrency)}
      ${escapeHtml(productPrice)}
    </p>

    <p>${escapeHtml(hostname)}</p>

    <small>
      Extraction:
      ${escapeHtml(extractionSource)}
      · Confidence:
      ${escapeHtml(confidence)}
    </small>
  `;

  statusNode.textContent =
    confidence === "HIGH"
      ? "Product detected"
      : "Needs review";

  analyzeButton.disabled = !(
    product.name
    && product.price !== null
    && product.price !== undefined
  );
}


async function scanActiveTab() {
  const tabs = await chrome.tabs.query({
    active: true,
    currentWindow: true,
  });

  const activeTab = tabs[0];

  if (!activeTab?.id) {
    throw new Error(
      "No active browser tab was found",
    );
  }

  try {
    const response =
      await chrome.tabs.sendMessage(
        activeTab.id,
        {
          type: "SCAN_CURRENT_PAGE",
        },
      );

    if (!response) {
      throw new Error(
        "The current page did not return product data",
      );
    }

    renderProduct(response);
  } catch {
    const storedData =
      await chrome.storage.local.get(
        "guardianLastScan",
      );

    if (!storedData.guardianLastScan) {
      throw new Error(
        "This page cannot be scanned. "
        + "Refresh the product page and try again.",
      );
    }

    renderProduct(
      storedData.guardianLastScan,
    );
  }
}


analyzeButton.addEventListener(
  "click",
  () => {
    if (!evidence) {
      errorNode.textContent =
        "No product evidence is available.";

      return;
    }

    analyzeButton.disabled = true;
    analyzeButton.textContent =
      "Analyzing...";

    errorNode.textContent = "";
    resultNode.classList.add("hidden");
    resultNode.innerHTML = "";

    chrome.runtime.sendMessage(
      {
        type: "ANALYZE_PRODUCT",
        evidence,
      },
      (response) => {
        analyzeButton.disabled = false;
        analyzeButton.textContent =
          "Analyze with Guardian";

        if (chrome.runtime.lastError) {
          errorNode.textContent =
            chrome.runtime.lastError.message
            || "Unable to contact the extension service.";

          return;
        }

        if (!response?.ok) {
          errorNode.textContent =
            response?.error
            || "Guardian analysis failed.";

          return;
        }

        const body = response.body ?? {};

        const decision =
          body.decision || "REVIEW";

        const merchantStatus =
          body.merchant_status
          || "UNKNOWN";

        const trustLevel =
          body.trust_level
          || "UNKNOWN";

        const explanation =
          body.explanation
          || "No explanation was returned.";

        const reasonCodes =
          Array.isArray(body.reason_codes)
            ? body.reason_codes
            : [];

        resultNode.classList.remove(
          "hidden",
        );

        resultNode.innerHTML = `
          <h2>Guardian result</h2>

          <p
            class="decision ${escapeHtml(decision)}"
          >
            ${escapeHtml(decision)}
          </p>

          <p>
            Merchant:
            ${escapeHtml(merchantStatus)}
          </p>

          <p>
            Trust:
            ${escapeHtml(trustLevel)}
          </p>

          <p>
            ${escapeHtml(explanation)}
          </p>

          <small>
            ${escapeHtml(
              reasonCodes.join(", "),
            )}
          </small>
        `;
      },
    );
  },
);


scanActiveTab().catch((error) => {
  errorNode.textContent =
    error instanceof Error
      ? error.message
      : "Unable to scan the current page.";

  statusNode.textContent =
    "Unavailable";

  analyzeButton.disabled = true;
});