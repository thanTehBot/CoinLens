const { useState } = React;
const h = React.createElement;

const COINS = [
  {
    name: "US Penny",
    description: "A one-cent coin with Abraham Lincoln on the front.",
    historyFact: "The Lincoln penny was first released in 1909 for Lincoln's 100th birthday."
  },
  {
    name: "US Nickel",
    description: "A five-cent coin with Thomas Jefferson on the front.",
    historyFact: "The modern Jefferson nickel design began in 1938."
  },it 
  {
    name: "US Dime",
    description: "A ten-cent coin that is the smallest current U.S. coin by size.",
    historyFact: "The Roosevelt dime was introduced in 1946 after President Franklin D. Roosevelt died."
  },
  {
    name: "US Quarter",
    description: "A twenty-five-cent coin with George Washington on the front.",
    historyFact: "The Washington quarter was first issued in 1932 for Washington's 200th birthday."
  },
  {
    name: "Wheat Penny",
    description: "An older Lincoln penny with two wheat stalks on the back.",
    historyFact: "Wheat pennies were minted from 1909 through 1958."
  }
];

function randomItem(items) {
  return items[Math.floor(Math.random() * items.length)];
}

function randomConfidence() {
  const minimum = Math.random() < 0.8 ? 0.72 : 0.4;
  return Number((minimum + Math.random() * (0.99 - minimum)).toFixed(2));
}

function getAlternatives(selectedCoin) {
  return COINS
    .filter((coin) => coin.name !== selectedCoin.name)
    .sort(() => Math.random() - 0.5)
    .slice(0, Math.random() < 0.5 ? 2 : 3)
    .map((coin) => coin.name);
}

function identifyCoinFake(imageInput) {
  // imageInput is intentionally ignored for now.
  const selectedCoin = randomItem(COINS);

  return {
    coinName: selectedCoin.name,
    confidenceScore: randomConfidence(),
    description: selectedCoin.description,
    historyFact: selectedCoin.historyFact,
    alternatives: getAlternatives(selectedCoin)
  };
}

function CoinResult({ result }) {
  if (!result) {
    return h(
      "section",
      { className: "empty-result", "aria-live": "polite" },
      h("h2", null, "No coin identified yet"),
      h("p", null, "Upload any image or press the button to generate a fake result.")
    );
  }

  return h(
    "section",
    { className: "result-card", "aria-live": "polite" },
    h(
      "div",
      { className: "result-header" },
      h("div", null, h("p", { className: "label" }, "Fake match"), h("h2", null, result.coinName)),
      h(
        "div",
        { className: "confidence" },
        h("strong", null, `${Math.round(result.confidenceScore * 100)}%`),
        h("span", null, "confidence")
      )
    ),
    h(
      "div",
      { className: "details" },
      h("p", null, h("span", null, "Description"), result.description),
      h("p", null, h("span", null, "History fact"), result.historyFact)
    ),
    h(
      "div",
      { className: "alternatives" },
      h("span", null, "Alternative possible coins"),
      h(
        "ul",
        null,
        result.alternatives.map((coin) => h("li", { key: coin }, coin))
      )
    )
  );
}

function FakeCoinIdentifier() {
  const [imageName, setImageName] = useState("");
  const [result, setResult] = useState(null);
  const [isLoading, setIsLoading] = useState(false);

  function handleImageChange(event) {
    const file = event.target.files?.[0];
    setImageName(file?.name || "");
  }

  function handleIdentify() {
    setIsLoading(true);

    window.setTimeout(() => {
      setResult(identifyCoinFake());
      setIsLoading(false);
    }, 750);
  }

  return h(
    "main",
    { className: "app-shell" },
    h(
      "section",
      { className: "scan-card" },
      h("p", { className: "label" }, "CoinLens placeholder"),
      h("h1", null, "Fake coin identifier"),
      h(
        "p",
        { className: "intro" },
        "This test feature ignores the image and randomly returns one coin from a fixed list."
      ),
      h(
        "label",
        { className: "upload-box" },
        h("span", null, imageName || "Choose a coin image"),
        h("input", { type: "file", accept: "image/*", onChange: handleImageChange })
      ),
      h(
        "button",
        {
          className: "primary-button",
          type: "button",
          onClick: handleIdentify,
          disabled: isLoading
        },
        isLoading ? "Identifying..." : "Identify coin"
      )
    ),
    h(CoinResult, { result })
  );
}

const root = ReactDOM.createRoot(document.querySelector("#root"));
root.render(h(FakeCoinIdentifier));
