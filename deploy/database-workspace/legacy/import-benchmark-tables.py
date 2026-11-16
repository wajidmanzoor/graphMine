"""Import canonical benchmark tables and prepare complete Neo4j bulk inputs."""

import argparse

from benchmark_import import Builder, ident, literal


def movielens_32m(b):
    b.materialize("ratings_input", f"SELECT userId::BIGINT AS userId,movieId::BIGINT AS movieId,rating::DOUBLE AS rating,timestamp::BIGINT AS timestamp FROM {b.csv('ratings.csv')}")
    b.materialize("tags_input", f"SELECT userId::BIGINT AS userId,movieId::BIGINT AS movieId,(row_number() OVER ()-1)::BIGINT AS tag_id,tag,timestamp::BIGINT AS timestamp FROM {b.csv('tags.csv')}")
    b.table("movies", f"SELECT movieId::BIGINT AS movieId,title,genres FROM {b.csv('movies.csv')}", key="movieId", labels=["Movie"])
    b.table("users", "SELECT userId FROM ratings_input UNION SELECT userId FROM tags_input", key="userId", labels=["User"])
    b.table("genres", f"SELECT genre AS name FROM {b.csv('genres.csv')}", key="name", labels=["Genre"])
    b.relationship("ratings", "SELECT * FROM ratings_input", ("users", "userId"), ("movies", "movieId"), "userId", "movieId", "RATED")
    b.relationship("tags", "SELECT * FROM tags_input", ("users", "userId"), ("movies", "movieId"), "userId", "movieId", "TAGGED")
    b.relationship("has_genre", f"SELECT src::BIGINT AS movieId,dst AS genre FROM {b.csv('has_genre_edge.csv')}", ("movies", "movieId"), ("genres", "name"), "movieId", "genre", "HAS_GENRE")
    b.table("links", f"SELECT movieId::BIGINT AS movieId,imdbId,tmdbId FROM {b.csv('links.csv')}")


def yelp(b):
    b.table("businesses", f"SELECT *,business_id AS id,stars AS rating FROM {b.json('yelp_academic_dataset_business.json')}", key="business_id", labels=["Business"])
    b.table("users", f"SELECT * FROM {b.json('yelp_academic_dataset_user.json')}", key="user_id", labels=["User"])
    b.table("reviews", f"SELECT *,review_id AS id FROM {b.json('yelp_academic_dataset_review.json')}", key="review_id", labels=["Review"])
    b.table("tips", f"SELECT * FROM {b.json('yelp_tip.json')}", key="tip_id", labels=["Tip"])
    b.table("categories", f"SELECT DISTINCT category AS name FROM {b.csv('yelp_categories.csv')}", key="name", labels=["Category"])
    b.relationship("wrote", "SELECT user_id,review_id FROM reviews", ("users", "user_id"), ("reviews", "review_id"), "user_id", "review_id", "WROTE")
    b.relationship("reviews_business", "SELECT review_id,business_id FROM reviews", ("reviews", "review_id"), ("businesses", "business_id"), "review_id", "business_id", "REVIEWS")
    b.relationship("tipped", "SELECT user_id,tip_id FROM tips", ("users", "user_id"), ("tips", "tip_id"), "user_id", "tip_id", "TIPPED")
    b.relationship("tip_for", "SELECT tip_id,business_id FROM tips", ("tips", "tip_id"), ("businesses", "business_id"), "tip_id", "business_id", "FOR")
    b.relationship("in_category", f"SELECT business_id,category FROM {b.csv('category_edges.csv')}", ("businesses", "business_id"), ("categories", "name"), "business_id", "category", "IN_CATEGORY")
    b.relationship("friends", f"SELECT src,dst FROM {b.csv('friend_edges.csv')}", ("users", "user_id"), ("users", "user_id"), "src", "dst", "FRIEND")
    b.table("checkins", f"SELECT * FROM {b.json('yelp_academic_dataset_checkin.json')}")


def movielens_genome(b):
    b.materialize("ratings_input", f"SELECT item_id::BIGINT AS item_id,user_id::BIGINT AS user_id,rating::DOUBLE AS rating FROM {b.json('ratings.json')}")
    b.materialize("surveys_input", f"SELECT * FROM {b.json('surveys_id.json')}")
    b.table("movies", f"SELECT * FROM {b.json('metadata.json')}", key="item_id", labels=["Movie"])
    b.table("users", "SELECT user_id FROM ratings_input UNION SELECT user_id FROM surveys_input", key="user_id", labels=["User"])
    b.table("tags", f"SELECT id AS tag_id,tag FROM {b.json('tags.json')}", key="tag_id", labels=["Tag"])
    b.table("reviews", f"SELECT review_id,item_id,txt AS text FROM {b.json('review_with_id.json')}", key="review_id", labels=["Review"])
    b.table("surveys", "SELECT * FROM surveys_input", key="survey_id", labels=["Survey"])
    b.table("directors", f"SELECT DISTINCT id AS name FROM {b.json('director_vertices.json')}", key="name", labels=["Director"])
    b.table("actors", f"SELECT DISTINCT id AS name FROM {b.json('actor_vertices.json')}", key="name", labels=["Actor"])
    b.relationship("ratings", "SELECT * FROM ratings_input", ("users", "user_id"), ("movies", "item_id"), "user_id", "item_id", "RATED")
    b.relationship("has_tag", f"SELECT item_id,tag_id,num AS count FROM {b.json('tag_count.json')}", ("movies", "item_id"), ("tags", "tag_id"), "item_id", "tag_id", "HAS_TAG")
    b.relationship("has_review", "SELECT item_id,review_id FROM reviews", ("movies", "item_id"), ("reviews", "review_id"), "item_id", "review_id", "HAS_REVIEW")
    b.relationship("answered", "SELECT user_id,survey_id FROM surveys", ("users", "user_id"), ("surveys", "survey_id"), "user_id", "survey_id", "ANSWERED")
    b.relationship("about_movie", "SELECT survey_id,item_id FROM surveys", ("surveys", "survey_id"), ("movies", "item_id"), "survey_id", "item_id", "ABOUT_MOVIE")
    b.relationship("about_tag", "SELECT survey_id,tag_id FROM surveys", ("surveys", "survey_id"), ("tags", "tag_id"), "survey_id", "tag_id", "ABOUT_TAG")
    b.relationship("directed", f"SELECT src,dst FROM {b.json('director_movie_edges.json')}", ("directors", "name"), ("movies", "item_id"), "src", "dst", "DIRECTED")
    b.relationship("acted_in", f"SELECT src,dst FROM {b.json('actor_movie_edge.json')}", ("actors", "name"), ("movies", "item_id"), "src", "dst", "ACTED_IN")


def ontime(b):
    paths = sorted(b.raw.glob("20??_*.csv"))
    if len(paths) != 36:
        raise RuntimeError("All 36 published OnTime monthly files are required")
    reader = f"read_csv([{','.join(literal(p) for p in paths)}], header=true,all_varchar=true,union_by_name=true)"
    fields = [row[0] for row in b.db.execute("DESCRIBE SELECT * FROM " + reader).fetchall()]
    numeric = {
        "Year", "Quarter", "Month", "DayofMonth", "DayOfWeek", "DOT_ID_Reporting_Airline",
        "OriginAirportID", "OriginAirportSeqID", "OriginCityMarketID", "OriginWac",
        "DestAirportID", "DestAirportSeqID", "DestCityMarketID", "DestWac",
        "CRSDepTime", "DepTime", "DepDelay", "DepDelayMinutes", "DepDel15",
        "TaxiOut", "TaxiIn", "CRSArrTime", "ArrTime", "ArrDelay", "ArrDelayMinutes",
        "ArrDel15", "Cancelled", "Diverted", "CRSElapsedTime", "ActualElapsedTime",
        "AirTime", "Flights", "Distance", "DistanceGroup", "CarrierDelay",
        "WeatherDelay", "NASDelay", "SecurityDelay", "LateAircraftDelay",
        "TotalAddGTime", "LongestAddGTime",
    }
    selections = [
        f"TRY_CAST({ident(f)} AS {'BIGINT' if f.endswith('ID') else 'DOUBLE'}) AS {ident(f)}" if f in numeric else
        f"{ident(f)}::DATE AS {ident(f)}" if f == "FlightDate" else ident(f)
        for f in fields
    ]
    b.materialize("flights_input", f"SELECT row_number() OVER ()::BIGINT AS flight_id,{','.join(selections)} FROM {reader}")
    airports = """
        SELECT airport_id::BIGINT AS airport_id,arg_max(code,day) AS code,
               arg_max(city,day) AS city,arg_max(state,day) AS state,arg_max(stateName,day) AS stateName
        FROM (
          SELECT OriginAirportID AS airport_id,Origin AS code,OriginCityName AS city,OriginState AS state,OriginStateName AS stateName,FlightDate AS day FROM flights_input
          UNION ALL
          SELECT DestAirportID,Dest,DestCityName,DestState,DestStateName,FlightDate FROM flights_input
        ) GROUP BY airport_id
    """
    b.table("airports", airports, key="airport_id", labels=["Airport"])
    b.relationship("flights", "SELECT * EXCLUDE(FlightDate),FlightDate AS flightDate,IATA_CODE_Reporting_Airline AS airline,Flight_Number_Reporting_Airline AS flightNumber FROM flights_input", ("airports", "airport_id"), ("airports", "airport_id"), "OriginAirportID", "DestAirportID", "FLIGHT")


def stackoverflow(b):
    def source(filename, key):
        # Pin the publisher's quoting; cleaned exports mix newline conventions.
        # Never skip rejected rows. Preserve incomplete original tails separately.
        options = {
            "strict_mode": "true" if filename in {"posts_answers.csv", "posts_questions.csv"} else "false",
            "null_padding": "true", "parallel": "false",
            "quote": literal('"'), "escape": literal('"'), "comment": "''",
        } if filename.startswith("posts_") else {}
        reader = b.csv(filename, delim="','", repair_truncated_tail=filename.startswith("posts_"), **options)
        columns = [r[0] for r in b.db.execute("DESCRIBE SELECT * FROM " + reader).fetchall()]
        numeric = {"age", "reputation", "up_votes", "down_votes", "views", "score", "count",
                   "class", "answer_count", "comment_count", "favorite_count", "view_count"}
        expressions = []
        for column in columns:
            field = ident(column)
            if column == "id":
                expressions.append(f"{field}::BIGINT AS {ident(key)}")
            elif column.endswith("_id") or column in numeric:
                expressions.append(f"TRY_CAST({field} AS BIGINT) AS {field}")
            elif column == "tag_based":
                expressions.append(f"TRY_CAST({field} AS BOOLEAN) AS {field}")
            else:
                expressions.append(field)
        return f"SELECT {','.join(expressions)} FROM {reader}"

    specifications = [
        ("users", "users_clean.csv", "user_id", "User"),
        ("badges", "badges.csv", "badge_id", "Badge"),
        ("comments", "comments_final.csv", "comment_id", "Comment"),
        ("votes", "votes.csv", "vote_id", "Vote"),
        ("answers", "posts_answers.csv", "post_id", "Post_answer"),
        ("questions", "posts_questions.csv", "post_id", "Post_question"),
        ("tags", "tags.csv", "tag_id", "Tag"),
        ("tag_wiki", "posts_tag_wiki_fixed.csv", "post_id", "Post_tag_wiki"),
        ("tag_wiki_excerpt", "posts_tag_wiki_excerpt_fixed.csv", "post_id", "Post_tag_wiki_excerpt"),
    ]
    for name, filename, key, label in specifications:
        if name == "questions":
            # The original has body/title for a subset; the complete cleaned
            # metadata export adds the remaining question IDs.
            for variant, original in [
                ("questions_publisher_original", "posts_questions.csv"),
                ("questions_publisher_cleaned_variant", "posts_questions_cleaned1.csv"),
            ]:
                b.table(variant, source(original, key), key=key, labels=[label])
                b.relational_only(variant)
            query = """
                SELECT * EXCLUDE(_gm_node_id) FROM questions_publisher_original
                UNION ALL BY NAME
                SELECT c.* EXCLUDE(_gm_node_id)
                FROM questions_publisher_cleaned_variant c
                ANTI JOIN questions_publisher_original o USING(post_id)
            """
            b.table(name, query, key=key, labels=[label])
            missing = b.db.execute(
                "SELECT count(*) FROM questions WHERE body IS NULL"
            ).fetchone()[0]
            b.manifest.setdefault("source_notes", [])
            note = {"filename": "posts_questions_cleaned1.csv",
                    "note": f"{missing:,} questions are available only as published metadata; their body and title are absent from the original export."}
            b.manifest["source_notes"] = [
                row for row in b.manifest["source_notes"] if row["filename"] != note["filename"]
            ] + [note]
            continue
        b.table(name, source(filename, key), key=key, labels=[label])
    for name, kind in [("questions", "OWNED_BY"), ("answers", "ANSWERS_BY"),
                       ("tag_wiki", "CREATED_BY"), ("tag_wiki_excerpt", "CREATED_BY")]:
        b.relationship(f"{name}_owner", f"SELECT post_id,owner_user_id FROM {name}",
                       (name, "post_id"), ("users", "user_id"), "post_id", "owner_user_id", kind)
        b.relationship(f"{name}_editor", f"SELECT post_id,last_editor_user_id FROM {name}",
                       (name, "post_id"), ("users", "user_id"), "post_id", "last_editor_user_id", "LAST_EDITED_BY")
    b.relationship("earned", "SELECT user_id,badge_id FROM badges", ("users", "user_id"), ("badges", "badge_id"), "user_id", "badge_id", "EARNED")
    b.relationship("answers_to", "SELECT post_id,parent_id FROM answers", ("answers", "post_id"), ("questions", "post_id"), "post_id", "parent_id", "ANSWERS_TO")
    b.relationship("accepts", "SELECT post_id,accepted_answer_id FROM questions", ("questions", "post_id"), ("answers", "post_id"), "post_id", "accepted_answer_id", "ACCEPTS")
    b.relationship("commented_by", "SELECT comment_id,user_id FROM comments", ("comments", "comment_id"), ("users", "user_id"), "comment_id", "user_id", "COMMENTED_BY")
    for name, kind in [("questions", "ON_QUESTION"), ("answers", "ON_ANSWER")]:
        b.relationship(f"comments_{name}", "SELECT comment_id,post_id FROM comments", ("comments", "comment_id"), (name, "post_id"), "comment_id", "post_id", kind)
        b.relationship(f"votes_{name}", "SELECT vote_id,post_id FROM votes", ("votes", "vote_id"), (name, "post_id"), "vote_id", "post_id", "VOTE_ON")
    b.relationship("tag_to", f"SELECT src::BIGINT AS tag_id,dst::BIGINT AS post_id FROM {b.csv('edge_tag_to_question.csv')}",
                   ("tags", "tag_id"), ("questions", "post_id"), "tag_id", "post_id", "TAG_TO")
    for name, column, kind in [("tag_wiki", "wiki_post_id", "HAS_WIKI"),
                               ("tag_wiki_excerpt", "excerpt_post_id", "HAS_WIKI_EXCERPT")]:
        b.relationship(f"tags_{name}", f"SELECT tag_id,{column} FROM tags", ("tags", "tag_id"), (name, "post_id"), "tag_id", column, kind)
    b.relationship("links", source("posts_links.csv", "post_link_id"),
                   ("questions", "post_id"), ("questions", "post_id"), "post_id", "related_post_id", "LINK_TO")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", choices=["yelp", "movielens-32m", "movielens-genome", "ontime", "stackoverflow"])
    args = parser.parse_args()
    builder = Builder(args.dataset)
    globals()[args.dataset.replace("-", "_")](builder)
    builder.finish()
