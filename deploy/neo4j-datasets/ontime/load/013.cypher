// Source: https://pgraphbenchweb.vercel.app/workloads/ontime-neo4j.html
// Copied: 2026-11-15T22:51:58+00:00
// Published code block: 2
// Path change: ${FILE} -> 2020_12.csv; expands the publisher's year/month loop.
CALL apoc.periodic.iterate(
  "
  LOAD CSV WITH HEADERS FROM 'file:///ontime20-22/2020_12.csv' AS row
  RETURN row
  ",
  "
  MATCH (origin:Airport {airport_id: toInteger(row.OriginAirportID)})
  MATCH (dest:Airport {airport_id: toInteger(row.DestAirportID)})
  MERGE (origin)-[f:FLIGHT {
      flightDate: date(row.FlightDate),
      airline: row.IATA_CODE_Reporting_Airline,
      flightNumber: row.Flight_Number_Reporting_Airline
  }]->(dest)
  SET f.Year = toInteger(row.Year),
      f.Quarter = toInteger(row.Quarter),
      f.Month = toInteger(row.Month),
      f.DayofMonth = toInteger(row.DayofMonth),
      f.DayOfWeek = toInteger(row.DayOfWeek),
      f.FlightDate = date(row.FlightDate),
      f.Reporting_Airline = row.Reporting_Airline,
      f.DOT_ID_Reporting_Airline = toInteger(row.DOT_ID_Reporting_Airline),
      f.IATA_CODE_Reporting_Airline = row.IATA_CODE_Reporting_Airline,
      f.Tail_Number = row.Tail_Number,
      f.Flight_Number_Reporting_Airline = row.Flight_Number_Reporting_Airline,
      f.OriginAirportID = toInteger(row.OriginAirportID),
      f.OriginAirportSeqID = toInteger(row.OriginAirportSeqID),
      f.OriginCityMarketID = toInteger(row.OriginCityMarketID),
      f.Origin = row.Origin,
      f.OriginCityName = row.OriginCityName,
      f.OriginState = row.OriginState,
      f.OriginStateFips = row.OriginStateFips,
      f.OriginStateName = row.OriginStateName,
      f.OriginWac = toInteger(row.OriginWac),
      f.DestAirportID = toInteger(row.DestAirportID),
      f.DestAirportSeqID = toInteger(row.DestAirportSeqID),
      f.DestCityMarketID = toInteger(row.DestCityMarketID),
      f.Dest = row.Dest,
      f.DestCityName = row.DestCityName,
      f.DestState = row.DestState,
      f.DestStateFips = row.DestStateFips,
      f.DestStateName = row.DestStateName,
      f.DestWac = toInteger(row.DestWac),
      f.CRSDepTime = toInteger(row.CRSDepTime),
      f.DepTime = toInteger(row.DepTime),
      f.DepDelay = toInteger(row.DepDelay),
      f.DepDelayMinutes = toInteger(row.DepDelayMinutes),
      f.DepDel15 = toInteger(row.DepDel15),
      f.DepartureDelayGroups = row.DepartureDelayGroups,
      f.DepTimeBlk = row.DepTimeBlk,
      f.TaxiOut = toInteger(row.TaxiOut),
      f.WheelsOff = row.WheelsOff,
      f.WheelsOn = row.WheelsOn,
      f.TaxiIn = toInteger(row.TaxiIn),
      f.CRSArrTime = toInteger(row.CRSArrTime),
      f.ArrTime = toInteger(row.ArrTime),
      f.ArrDelay = toInteger(row.ArrDelay),
      f.ArrDelayMinutes = toInteger(row.ArrDelayMinutes),
      f.ArrDel15 = toInteger(row.ArrDel15),
      f.ArrivalDelayGroups = row.ArrivalDelayGroups,
      f.ArrTimeBlk = row.ArrTimeBlk,
      f.Cancelled = toInteger(row.Cancelled),
      f.CancellationCode = row.CancellationCode,
      f.Diverted = toInteger(row.Diverted),
      f.CRSElapsedTime = toInteger(row.CRSElapsedTime),
      f.ActualElapsedTime = toInteger(row.ActualElapsedTime),
      f.AirTime = toInteger(row.AirTime),
      f.Flights = toInteger(row.Flights),
      f.Distance = toInteger(row.Distance),
      f.DistanceGroup = toInteger(row.DistanceGroup),
      f.CarrierDelay = toInteger(row.CarrierDelay),
      f.WeatherDelay = toInteger(row.WeatherDelay),
      f.NASDelay = toInteger(row.NASDelay),
      f.SecurityDelay = toInteger(row.SecurityDelay),
      f.LateAircraftDelay = toInteger(row.LateAircraftDelay),
      f.FirstDepTime = toInteger(row.FirstDepTime),
      f.TotalAddGTime = toInteger(row.TotalAddGTime),
      f.LongestAddGTime = toInteger(row.LongestAddGTime)
  ",
  {batchSize:1000, parallel:false}
) YIELD batches, total, timeTaken, committedOperations, failedOperations
RETURN batches, total, timeTaken/1000.0 AS seconds, committedOperations, failedOperations;