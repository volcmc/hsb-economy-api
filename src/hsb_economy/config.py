HYPIXEL_API = "https://api.hypixel.net/v2/skyblock"
AUCTIONS_URL = f"{HYPIXEL_API}/auctions"
AUCTIONS_ENDED_URL = f"{HYPIXEL_API}/auctions_ended"
BAZAAR_URL = f"{HYPIXEL_API}/bazaar"
ITEMS_URL = "https://api.hypixel.net/v2/resources/skyblock/items"

# Published URL layout. Bump when the output schema changes incompatibly.
API_VERSION = "v1"

REQUEST_TIMEOUT = 30.0
REQUEST_RETRIES = 4
PAGE_CONCURRENCY = 10
# Hypixel regenerates the auction pages roughly once a minute. Pages behind the newest update are
# refetched up to SNAPSHOT_ATTEMPTS times, SNAPSHOT_RETRY_DELAY seconds apart.
SNAPSHOT_ATTEMPTS = 4
SNAPSHOT_RETRY_DELAY = 5.0

# auctions_ended only covers the most recent 60 seconds of sales.
ENDED_WINDOW_SECONDS = 60
# Must not exceed MAX_PAGE_SIZE in worker/src/index.ts.
SALES_FEED_PAGE_SIZE = 60
# The Worker captures every minute, so a newest response older than this means its cron has stopped.
SALES_FEED_MAX_AGE_SECONDS = 300
# Below this much observed sales time in a day, scaling sample counts up to a daily volume is noise.
MIN_OBSERVED_SECONDS_FOR_VOLUME = 3_600

HOUR = 3_600
DAY = 86_400
SALES_RETENTION = 7 * DAY
# How long an unlisted item keeps reporting its last lowest BIN.
LAST_SEEN_RETENTION = 30 * DAY
SEEN_SALE_IDS_LIMIT = 5_000
HOURLY_RETENTION = 7 * DAY
DAILY_RETENTION = 365 * DAY

# Pet levels that get their own lowest-BIN entry.
PET_LEVEL_BUCKETS = (1, 100, 200)
