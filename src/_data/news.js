const path = require("path");

module.exports = function () {
  // Clear require cache so a watch-mode rebuild picks up the latest JSON
  const jsonPath = path.resolve(__dirname, "../../data/news.json");
  delete require.cache[jsonPath];
  try {
    return require(jsonPath);
  } catch {
    return { generated_at: null, article_count: 0, categories: {}, articles: [] };
  }
};
