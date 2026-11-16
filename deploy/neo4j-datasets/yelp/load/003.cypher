// Source: https://pgraphbenchweb.vercel.app/workloads/yelp-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 3
CALL apoc.periodic.iterate(
  "CALL apoc.load.json('file:///yelp/yelp_academic_dataset_user.json') YIELD value",
  "CREATE (u:User {
      user_id: value.user_id,
      name: value.name,
      review_count: value.review_count,
      yelping_since: value.yelping_since,
      friends: value.friends,
      useful: value.useful,
      funny: value.funny,
      cool: value.cool,
      fans: value.fans,
      elite: value.elite,
      average_stars: value.average_stars,
      compliment_hot: value.compliment_hot,
      compliment_more: value.compliment_more,
      compliment_profile: value.compliment_profile,
      compliment_cute: value.compliment_cute,
      compliment_list: value.compliment_list,
      compliment_note: value.compliment_note,
      compliment_plain: value.compliment_plain,
      compliment_cool: value.compliment_cool,
      compliment_funny: value.compliment_funny,
      compliment_writer: value.compliment_writer,
      compliment_photos: value.compliment_photos
    })",
  {batchSize: 1000, parallel: true}
)