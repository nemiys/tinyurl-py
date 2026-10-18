-- Cassandra schema. Applied by the `cassandra-init` service in docker-compose.yml.
-- Every statement is IF NOT EXISTS, so running this file again is harmless.

-- A keyspace is Cassandra's "database". One copy of each row is enough on a
-- single local node; a real cluster would keep 3.
CREATE KEYSPACE IF NOT EXISTS tinyurl
  WITH replication = {'class': 'SimpleStrategy', 'replication_factor': 1};

-- One row per click. Designed around the question we ask most:
-- "clicks of link X on day Y".
--   partition key (link_id, day): all clicks of one link on one day live together
--   clustering columns (clicked_at, event_id): their order inside that partition
-- Writing the same key twice overwrites the row, so a redelivered event
-- (same event_id) can never create a duplicate click.
CREATE TABLE IF NOT EXISTS tinyurl.clicks_by_link_day (
  link_id    text,
  day        date,
  clicked_at timestamp,
  event_id   uuid,
  device     text,
  PRIMARY KEY ((link_id, day), clicked_at, event_id)
) WITH CLUSTERING ORDER BY (clicked_at DESC, event_id ASC);
