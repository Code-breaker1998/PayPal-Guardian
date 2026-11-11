(() => {
  const text = (value) => (typeof value === "string" ? value.trim() : "");
  const first = (...values) => values.map(text).find(Boolean) || null;

  const meta = (selectors) => {
    for (const selector of selectors) {
      const element = document.querySelector(selector);
      const value = element?.getAttribute("content") || element?.textContent;
      if (text(value)) return text(value);
    }
    return null;
  };

  const numberFromText = (value) => {
    if (!value) return null;
    const normalized = String(value).replace(/,/g, "");
    const match = normalized.match(/(?:£|€|\$|₹|USD|GBP|EUR|INR)?\s*(\d+(?:\.\d{1,2})?)/i);
    return match ? Number(match[1]) : null;
  };

  const currencyFromText = (value) => {
    const source = String(value || "").toUpperCase();
    if (source.includes("GBP") || source.includes("£")) return "GBP";
    if (source.includes("EUR") || source.includes("€")) return "EUR";
    if (source.includes("INR") || source.includes("₹")) return "INR";
    if (source.includes("USD") || source.includes("$")) return "USD";
    return null;
  };

  const findProductNode = (value) => {
    if (Array.isArray(value)) {
      for (const child of value) {
        const result = findProductNode(child);
        if (result) return result;
      }
      return null;
    }
    if (!value || typeof value !== "object") return null;
    const type = value["@type"];
    const types = Array.isArray(type) ? type : [type];
    if (types.includes("Product") || types.includes("Book")) return value;
    if (value["@graph"]) {
      const graphResult = findProductNode(value["@graph"]);
      if (graphResult) return graphResult;
    }
    for (const child of Object.values(value)) {
      const result = findProductNode(child);
      if (result) return result;
    }
    return null;
  };

  const jsonLdProduct = () => {
    for (const script of document.querySelectorAll('script[type="application/ld+json"]')) {
      try {
        const node = findProductNode(JSON.parse(script.textContent || "null"));
        if (!node) continue;
        const offers = Array.isArray(node.offers) ? node.offers[0] : node.offers || {};
        const aggregateRating = node.aggregateRating || {};
        const brand = typeof node.brand === "object" ? node.brand?.name : node.brand;
        return {
          name: first(node.name),
          price: numberFromText(offers.price || offers.lowPrice),
          currency: first(offers.priceCurrency),
          sku: first(node.sku, node.productID, node.mpn, node.isbn),
          rating: numberFromText(aggregateRating.ratingValue),
          availability: first(offers.availability),
          seller_name: first(offers.seller?.name, brand),
          image_url: first(Array.isArray(node.image) ? node.image[0] : node.image),
          category: first(node.category),
          source: "JSON_LD"
        };
      } catch (_) {}
    }
    return null;
  };

  const genericProduct = () => {
    const priceText = first(
      meta(['meta[property="product:price:amount"]', 'meta[itemprop="price"]']),
      document.querySelector('[itemprop="price"]')?.getAttribute("content"),
      document.querySelector('[itemprop="price"]')?.textContent,
      document.querySelector('.product_main .price_color')?.textContent,
      document.querySelector('[class*="price"]')?.textContent
    );
    const name = first(
      meta(['meta[property="og:title"]', 'meta[name="twitter:title"]']),
      document.querySelector('[itemprop="name"]')?.textContent,
      document.querySelector('.product_main h1')?.textContent,
      document.querySelector('main h1')?.textContent,
      document.querySelector('h1')?.textContent,
      document.title
    );
    const currency = first(
      meta(['meta[property="product:price:currency"]', 'meta[itemprop="priceCurrency"]']),
      currencyFromText(priceText)
    );
    return {
      name,
      price: numberFromText(priceText),
      currency,
      sku: first(
        document.querySelector('[itemprop="sku"]')?.getAttribute("content"),
        document.querySelector('[itemprop="sku"]')?.textContent
      ),
      rating: numberFromText(
        first(
          document.querySelector('[itemprop="ratingValue"]')?.getAttribute("content"),
          document.querySelector('[itemprop="ratingValue"]')?.textContent
        )
      ),
      availability: first(
        document.querySelector('[itemprop="availability"]')?.getAttribute("href"),
        document.querySelector('.availability')?.textContent
      ),
      seller_name: first(
        document.querySelector('[itemprop="seller"] [itemprop="name"]')?.textContent,
        document.querySelector('[class*="seller"]')?.textContent,
        location.hostname
      ),
      image_url: first(
        meta(['meta[property="og:image"]']),
        document.querySelector('[itemprop="image"]')?.getAttribute("src")
      ),
      category: first(
        document.querySelector('[itemprop="category"]')?.textContent
      ),
      source: "GENERIC_DOM"
    };
  };

  const scan = () => {
    const product = jsonLdProduct() || genericProduct();
    const confidence = product.name && product.price !== null ? "HIGH" : product.name ? "MEDIUM" : "LOW";
    return {
      page_url: location.href,
      page_title: document.title,
      hostname: location.hostname,
      product,
      confidence,
      extracted_at: new Date().toISOString()
    };
  };

  const publish = async () => {
    const evidence = scan();
    await chrome.storage.local.set({ guardianLastScan: evidence });
    chrome.runtime.sendMessage({ type: "PAGE_SCAN_UPDATED", evidence });
  };

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "SCAN_CURRENT_PAGE") {
      sendResponse(scan());
    }
  });

  publish();
  setTimeout(publish, 1500);
})();
