// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 2
CALL apoc.periodic.iterate(
  "CALL apoc.load.json('file:///yelp/yelp_academic_dataset_business.json') YIELD value",
  "CREATE (b:Business {
      id: value.business_id,
      name: value.name,
      address: value.address,
      city: value.city,
      state: value.state,
      postal_code: value.postal_code,
      latitude: value.latitude,
      longitude: value.longitude,
      is_open: value.is_open,
      categories: value.categories,
      rating: value.stars,
      review_count: value.review_count
    })",
  {batchSize: 1000, parallel: true}
)