// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 1
CALL apoc.periodic.iterate(
"
  UNWIND [
    'file:///ontime20-22/2020_1.csv',
    'file:///ontime20-22/2020_2.csv',
    'file:///ontime20-22/2020_3.csv',
    'file:///ontime20-22/2020_4.csv',
    'file:///ontime20-22/2020_5.csv',
    'file:///ontime20-22/2020_6.csv',
    'file:///ontime20-22/2020_7.csv',
    'file:///ontime20-22/2020_8.csv',
    'file:///ontime20-22/2020_9.csv',
    'file:///ontime20-22/2020_10.csv',
    'file:///ontime20-22/2020_11.csv',
    'file:///ontime20-22/2020_12.csv',
    'file:///ontime20-22/2021_1.csv',
    'file:///ontime20-22/2021_2.csv',
    'file:///ontime20-22/2021_3.csv',
    'file:///ontime20-22/2021_4.csv',
    'file:///ontime20-22/2021_5.csv',
    'file:///ontime20-22/2021_6.csv',
    'file:///ontime20-22/2021_7.csv',
    'file:///ontime20-22/2021_8.csv',
    'file:///ontime20-22/2021_9.csv',
    'file:///ontime20-22/2021_10.csv',
    'file:///ontime20-22/2021_11.csv',
    'file:///ontime20-22/2021_12.csv',
    'file:///ontime20-22/2022_1.csv',
    'file:///ontime20-22/2022_2.csv',
    'file:///ontime20-22/2022_3.csv',
    'file:///ontime20-22/2022_4.csv',
    'file:///ontime20-22/2022_5.csv',
    'file:///ontime20-22/2022_6.csv',
    'file:///ontime20-22/2022_7.csv',
    'file:///ontime20-22/2022_8.csv',
    'file:///ontime20-22/2022_9.csv',
    'file:///ontime20-22/2022_10.csv',
    'file:///ontime20-22/2022_11.csv',
    'file:///ontime20-22/2022_12.csv'
  ] AS file
  LOAD CSV WITH HEADERS FROM file AS row
  WITH [
    {
      id: toInteger(row.OriginAirportID),
      code: row.Origin,
      city: row.OriginCityName,
      state: row.OriginState,
      stateName: row.OriginStateName
    },
    {
      id: toInteger(row.DestAirportID),
      code: row.Dest,
      city: row.DestCityName,
      state: row.DestState,
      stateName: row.DestStateName
    }
  ] AS airports
  UNWIND airports AS a
  WITH DISTINCT a.id AS airport_id, a.code AS code, a.city AS city, a.state AS state, a.stateName AS stateName
  RETURN airport_id, code, city, state, stateName
  ",
  "
  MERGE (ap:Airport {airport_id: airport_id})
  SET ap.code = code,
      ap.city = city,
      ap.state = state,
      ap.stateName = stateName
  ",
  {batchSize:1000, parallel:false}
);