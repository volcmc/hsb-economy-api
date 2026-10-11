// Hypixel's auctions_ended only covers the last 60 seconds, and GitHub Actions can run at most every
// 5 minutes. This Worker captures every response so the Pages pipeline can process all sales.

const ENDED_URL = "https://api.hypixel.net/v2/skyblock/auctions_ended";
// Hypixel regenerates the response about once a minute. Sampling twice per cron minute guarantees
// every version is captured despite clock drift; duplicates are ignored by the primary key.
const SECOND_CAPTURE_DELAY_MS = 30_000;
// Free-plan D1 databases cap at 500 MB and a day of responses is roughly 190 MB.
const RETENTION_MS = 36 * 60 * 60 * 1000;
const MAX_PAGE_SIZE = 60;

interface EndedResponse {
	success: boolean;
	lastUpdated: number;
}

async function capture(env: Env): Promise<void> {
	const response = await fetch(ENDED_URL, {
		headers: { "User-Agent": "hsb-economy-api (+https://github.com/volcmc/hsb-economy-api)" },
	});
	if (!response.ok) {
		throw new Error(`auctions_ended returned HTTP ${response.status}`);
	}
	const body = await response.text();
	// Parsing also rejects the truncated bodies Hypixel occasionally sends with a 200.
	const data = JSON.parse(body) as EndedResponse;
	if (!data.success || typeof data.lastUpdated !== "number") {
		throw new Error("auctions_ended responded without success");
	}
	await env.DB.prepare("INSERT OR IGNORE INTO ended (last_updated, body) VALUES (?, ?)")
		.bind(data.lastUpdated, body)
		.run();
}

async function captureLogged(env: Env): Promise<void> {
	try {
		await capture(env);
	} catch (error) {
		console.error("capture failed", error);
	}
}

async function authorized(request: Request, env: Env): Promise<boolean> {
	if (!env.SALES_TOKEN) {
		return false;
	}
	const encoder = new TextEncoder();
	const given = encoder.encode(request.headers.get("Authorization") ?? "");
	const expected = encoder.encode(`Bearer ${env.SALES_TOKEN}`);
	return given.byteLength === expected.byteLength && crypto.subtle.timingSafeEqual(given, expected);
}

async function listEnded(url: URL, env: Env): Promise<Response> {
	const after = Number(url.searchParams.get("after") ?? "0");
	const limit = Math.min(Number(url.searchParams.get("limit") ?? MAX_PAGE_SIZE), MAX_PAGE_SIZE);
	if (!Number.isSafeInteger(after) || !Number.isSafeInteger(limit) || limit < 1) {
		return new Response("Invalid after or limit", { status: 400 });
	}
	const { results } = await env.DB.prepare(
		"SELECT last_updated, body FROM ended WHERE last_updated > ? ORDER BY last_updated LIMIT ?",
	)
		.bind(after, limit + 1)
		.all<{ last_updated: number; body: string }>();
	const more = results.length > limit;
	const page = results.slice(0, limit);
	// Bodies are already JSON; splicing them avoids re-parsing megabytes within the CPU limit.
	const json = `{"more":${more},"responses":[${page.map((row) => row.body).join(",")}]}`;
	return new Response(json, { headers: { "Content-Type": "application/json" } });
}

export default {
	async fetch(request, env): Promise<Response> {
		const url = new URL(request.url);
		if (url.pathname !== "/ended" || request.method !== "GET") {
			return new Response("Not found", { status: 404 });
		}
		if (!(await authorized(request, env))) {
			return new Response("Unauthorized", { status: 401 });
		}
		return listEnded(url, env);
	},

	async scheduled(controller, env): Promise<void> {
		await captureLogged(env);
		await new Promise((resolve) => setTimeout(resolve, SECOND_CAPTURE_DELAY_MS));
		await captureLogged(env);
		await env.DB.prepare("DELETE FROM ended WHERE last_updated < ?")
			.bind(controller.scheduledTime - RETENTION_MS)
			.run();
	},
} satisfies ExportedHandler<Env>;
