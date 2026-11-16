// Source: https://pgraphbenchweb.vercel.app/workloads/snb-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 50

// Q13. Zombies in a country
MATCH (country:Country {name: $country})<-[:IS_PART_OF]-(:City)<-[:IS_LOCATED_IN]-(zombie:Person)
WHERE zombie.creationDate < $endDate
WITH country, zombie
OPTIONAL MATCH (zombie)<-[:HAS_CREATOR]-(message:Message)
WHERE message.creationDate < $endDate
WITH
  country,
  zombie,
  count(message) AS messageCount
WITH
  country,
  zombie,
  12 * ($endDate.year  - zombie.creationDate.year )
     + ($endDate.month - zombie.creationDate.month)
     + 1 AS months,
  messageCount
WHERE messageCount / months < 1
WITH
  country,
  collect(zombie) AS zombies
UNWIND zombies AS zombie
OPTIONAL MATCH
  (zombie)<-[:HAS_CREATOR]-(message:Message)<-[:LIKES]-(likerZombie:Person)
WHERE likerZombie IN zombies
WITH
  zombie,
  count(likerZombie) AS zombieLikeCount
OPTIONAL MATCH
  (zombie)<-[:HAS_CREATOR]-(message:Message)<-[:LIKES]-(likerPerson:Person)
WHERE likerPerson.creationDate < $endDate
WITH
  zombie,
  zombieLikeCount,
  count(likerPerson) AS totalLikeCount
RETURN
  zombie.id,
  zombieLikeCount,
  totalLikeCount,
  CASE totalLikeCount
    WHEN 0 THEN 0.0
    ELSE zombieLikeCount / toFloat(totalLikeCount)
  END AS zombieScore
ORDER BY
  zombieScore DESC,
  zombie.id ASC
LIMIT 100