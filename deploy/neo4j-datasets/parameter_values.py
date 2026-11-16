"""Concrete, recorded inputs for publisher queries that supply no parameter values."""


def values(slug, session):
    selectors = []
    def rows(query, **parameters):
        selectors.append({"query": query, "parameters": parameters})
        return session.run(query, parameters).data()
    if slug == "ontime":
        candidates = rows("MATCH (a:Airport)-[f:FLIGHT]->() WITH a, count(f) AS degree "
                          "RETURN a.airport_id AS id, degree ORDER BY degree, id LIMIT 1")
        if not candidates:
            raise ValueError("No connected airport is available for verification parameters")
        pair = rows("MATCH (a:Airport {airport_id:$id})-[f:FLIGHT]->(b:Airport) "
                    "RETURN a.airport_id AS source, b.airport_id AS target, a.code AS code, "
                    "a.state AS stateA, b.state AS stateB, f.Year AS year, toString(f.FlightDate) AS date LIMIT 1",
                    id=candidates[0]["id"])[0]
        result = {"originAirportId": pair["source"], "sourceAirportId": pair["source"], "targetAirportId": pair["target"],
                  "year": pair["year"], "Year": pair["year"], "date": pair["date"], "state": pair["stateA"],
                  "stateA": pair["stateA"], "stateB": pair["stateB"], "codePrefix": pair["code"][:1],
                  "limit": 20, "minDelayMinutes": 60, "minDistance": 1000, "minDegree": 2}
        selection = "Use a real outgoing flight from the airport with the smallest positive outgoing degree. Both airport IDs, year, date, states and code prefix come from that flight."
    elif slug == "ldbc-snb":
        pair = rows("MATCH (a:Person)-[:KNOWS]-(b:Person) "
                    "RETURN a.id AS source, b.id AS target, a.speaks AS languages LIMIT 1")
        countries = rows("MATCH (n:Country) RETURN n.name AS name ORDER BY n.id LIMIT 2")
        tags = rows("MATCH (n:Tag) RETURN n.name AS name ORDER BY n.id LIMIT 2")
        classes = rows("MATCH (n:TagClass) RETURN n.name AS name ORDER BY n.id LIMIT 1")
        if not pair or len(countries) < 2 or len(tags) < 2 or not classes or not pair[0]["languages"]:
            raise ValueError("The loaded graph does not supply the required LDBC parameter examples")
        a = pair[0]
        def moment(value): return {"type": "datetime", "value": value + "T00:00:00+00:00"}
        result = {"personId": a["source"], "person1Id": a["source"], "person2Id": a["target"],
                  "language": a["languages"][0], "languages": a["languages"], "limit": 20,
                  "birthday": {"type": "date", "value": "1980-01-01"},
                  "country": countries[0]["name"], "country1": countries[0]["name"], "country2": countries[1]["name"],
                  "tag": tags[0]["name"], "tagA": tags[0]["name"], "tagB": tags[1]["name"], "tagClass": classes[0]["name"],
                  "startDate": moment("2009-01-01"), "endDate": moment("2013-01-01"), "date": moment("2011-01-01"),
                  "datetime": moment("2013-01-01"), "dateA": moment("2011-01-01"), "dateB": moment("2012-01-01"),
                  "minDegree": 2, "lengthThreshold": 100, "minPathDistance": 1, "maxPathDistance": 2,
                  "maxKnowsLimit": 10, "delta": 24}
        selection = "Use a real KNOWS pair and its source person's language, plus countries, tags and a tag class selected from actual nodes. Temporal/filter values are explicit verification examples, not official performance-benchmark parameters."
    else:
        return {"default": {}, "queries": {}}
    return {"selection": selection, "selectors": selectors, "default": result, "queries": {}}
