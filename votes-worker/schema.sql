-- One row per voter. id is a hash of the browser's secret token; ip is a salted hash of the network,
-- used only to cap new votes per network per day.
CREATE TABLE IF NOT EXISTS votes (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL DEFAULT '',
  pick TEXT NOT NULL CHECK (pick IN ('yes', 'no')),
  level INTEGER NOT NULL,
  t INTEGER NOT NULL,
  switched INTEGER NOT NULL DEFAULT 0,
  created INTEGER NOT NULL,
  ip TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS votes_by_network ON votes (ip, created);
