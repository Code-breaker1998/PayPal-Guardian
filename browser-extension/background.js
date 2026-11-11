const AGENT_URL =
  "http://localhost:8100/agent/browser-extension-page/analyze";


chrome.runtime.onInstalled.addListener(() => {
  chrome.storage.local.set({
    guardianAutoScan: true,
  });
});


chrome.runtime.onMessage.addListener(
  (message, _sender, sendResponse) => {
    if (message?.type === "PAGE_SCAN_UPDATED") {
      const isHighConfidence =
        message.evidence?.confidence === "HIGH";

      chrome.action.setBadgeText({
        text: isHighConfidence ? "✓" : "?",
      });

      chrome.action.setBadgeBackgroundColor({
        color: isHighConfidence
          ? "#16a34a"
          : "#d97706",
      });

      return false;
    }

    if (message?.type !== "ANALYZE_PRODUCT") {
      return false;
    }

    fetch(AGENT_URL, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(
        message.evidence,
      ),
    })
      .then(async (response) => {
        let body;

        try {
          body = await response.json();
        } catch {
          body = {
            detail: await response.text(),
          };
        }

        if (!response.ok) {
          const errorMessage =
            typeof body.detail === "string"
              ? body.detail
              : JSON.stringify(
                  body.detail ?? body,
                );

          throw new Error(
            errorMessage
            || `Request failed with status ${response.status}`,
          );
        }

        sendResponse({
          ok: true,
          body,
        });
      })
      .catch((error) => {
        sendResponse({
          ok: false,
          error:
            error instanceof Error
              ? error.message
              : "Guardian analysis failed",
        });
      });

    return true;
  },
);