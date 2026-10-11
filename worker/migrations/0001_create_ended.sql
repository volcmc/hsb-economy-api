-- One row per distinct Hypixel auctions_ended response, stored verbatim.
CREATE TABLE ended (
    last_updated INTEGER PRIMARY KEY,
    body TEXT NOT NULL
);
