import { MetadataRoute } from "next";

const BASE_URL = "https://nrl-predictor.ohare.id.au";

export default function sitemap(): MetadataRoute.Sitemap {
  const staticRoutes: MetadataRoute.Sitemap = [
    { url: BASE_URL, lastModified: new Date(), changeFrequency: "daily", priority: 1 },
    { url: `${BASE_URL}/accuracy`, lastModified: new Date(), changeFrequency: "hourly", priority: 0.9 },
    { url: `${BASE_URL}/how-it-works`, lastModified: new Date(), changeFrequency: "monthly", priority: 0.5 },
  ];

  const roundRoutes: MetadataRoute.Sitemap = Array.from({ length: 27 }, (_, i) => ({
    url: `${BASE_URL}/predictions/${i + 1}`,
    lastModified: new Date(),
    changeFrequency: "hourly" as const,
    priority: 0.9,
  }));

  return [...staticRoutes, ...roundRoutes];
}
