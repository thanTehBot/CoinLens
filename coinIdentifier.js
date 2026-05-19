const coins = [
  {
    name: "US Quarter",
    keywords: ["quarter", "25 cents", "twenty five cents", "washington"],
    description: "A twenty-five-cent U.S. coin with George Washington on the front.",
    historyFact: "The Washington quarter was first issued in 1932."
  },
  {
    name: "Penny",
    keywords: ["penny", "1 cent", "one cent", "lincoln", "cent"],
    description: "A one-cent U.S. coin with Abraham Lincoln on the front.",
    historyFact: "The Lincoln penny was first released in 1909."
  },
  {
    name: "US Nickel",
    keywords: ["nickel", "5 cents", "five cents", "jefferson"],
    description: "A five-cent U.S. coin with Thomas Jefferson on the front.",
    historyFact: "The Jefferson nickel design began in 1938."
  },
  {
    name: "US Dime",
    keywords: ["dime", "10 cents", "ten cents", "roosevelt"],
    description: "A ten-cent U.S. coin that is smaller than the penny and nickel.",
    historyFact: "The Roosevelt dime was introduced in 1946."
  },
  {
    name: "Wheat Penny",
    keywords: ["wheat penny", "wheat cent", "wheat", "1909", "1958"],
    description: "An older Lincoln penny with wheat stalks on the reverse side.",
    historyFact: "Wheat pennies were minted from 1909 through 1958."
  }
];

function randomItem(items) {
  return items[Math.floor(Math.random() * items.length)];
}

function randomConfidence(minimum = 0.4) {
  return Number((minimum + Math.random() * (0.99 - minimum)).toFixed(2));
}

function getAlternatives(selectedCoin) {
  return coins
    .filter((coin) => coin.name !== selectedCoin.name)
    .sort(() => Math.random() - 0.5)
    .slice(0, 3)
    .map((coin) => coin.name);
}

function findCoinByKeywords(inputText) {
  const normalizedInput = String(inputText || "").trim().toLowerCase();

  if (!normalizedInput) {
    return null;
  }

  return coins.find((coin) =>
    coin.keywords.some((keyword) => normalizedInput.includes(keyword))
  );
}

export function identifyCoin(inputText, imageInput) {
  // imageInput is intentionally ignored until real image processing is added.
  const matchedCoin = findCoinByKeywords(inputText);
  const selectedCoin = matchedCoin || randomItem(coins);

  return {
    coinName: selectedCoin.name,
    confidenceScore: matchedCoin ? randomConfidence(0.82) : randomConfidence(0.4),
    description: selectedCoin.description,
    historyFact: selectedCoin.historyFact,
    alternatives: getAlternatives(selectedCoin),
    matchedByKeyword: Boolean(matchedCoin)
  };
}

export { coins };
