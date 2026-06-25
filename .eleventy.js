const { DateTime } = require("luxon");

module.exports = function (eleventyConfig) {
  // Make data/news.json available as global data
  eleventyConfig.addGlobalData("news", () => {
    try {
      return require("./data/news.json");
    } catch {
      return { generated_at: null, article_count: 0, categories: {}, articles: [] };
    }
  });

  // Format ISO date strings for display
  eleventyConfig.addFilter("readableDate", (isoString) => {
    if (!isoString) return "Unknown date";
    return DateTime.fromISO(isoString, { zone: "utc" }).toFormat("dd LLL yyyy, HH:mm") + " UTC";
  });

  eleventyConfig.addFilter("isoDate", (isoString) => {
    if (!isoString) return "";
    return DateTime.fromISO(isoString, { zone: "utc" }).toISO();
  });

  // Return first N items of an array
  eleventyConfig.addFilter("limit", (arr, n) => (Array.isArray(arr) ? arr.slice(0, n) : arr));

  // Slugify a category name for use in URLs
  eleventyConfig.addFilter("categorySlug", (str) => {
    return str
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "");
  });

  // Pass through static assets
  eleventyConfig.addPassthroughCopy("src/assets");

  return {
    dir: {
      input: "src",
      output: "_site",
      includes: "_includes",
      data: "_data",
    },
    templateFormats: ["njk", "html"],
    htmlTemplateEngine: "njk",
  };
};
