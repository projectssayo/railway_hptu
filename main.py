import json
import asyncio
import sys
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from playwright.async_api import async_playwright

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# ---- URLs ----
home = "https://results.indiaresults.com/hp/himtu/hp-himtu/mquery.aspx?id=1800266513"
sem_4_home = "https://himturesult.indiaresults.com/hp/himtu/hp-himtu/query.aspx?chk=Y&id=1800267004"

# ---- Railway / Docker hardening ----
# "Page crashed" on a server (but fine locally) is almost always Chromium running out of
# shared memory (/dev/shm is ~64MB in containers) or RAM. These flags + blocking heavy
# resources fix that; crash recovery below handles any that still slip through.
CHROMIUM_ARGS = [
    "--disable-dev-shm-usage",      # use /tmp instead of the tiny /dev/shm  (the big one)
    "--no-sandbox",
    "--disable-setuid-sandbox",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-default-apps",
    "--mute-audio",
    "--no-first-run",
]
NAV_TIMEOUT_MS = 45000
BLOCKED_TYPES = {"image", "media", "font"}
BLOCKED_HOSTS = ("google-analytics", "googletagmanager", "doubleclick", "googlesyndication",
                 "facebook", "adservice", "hotjar", "clarity.ms")

app = FastAPI()


async def _route_filter(route):
    req = route.request
    url = req.url.lower()
    if req.resource_type in BLOCKED_TYPES or any(h in url for h in BLOCKED_HOSTS):
        await route.abort()
    else:
        await route.continue_()


async def new_page(browser):
    """Fresh context+page with heavy stuff blocked. A crashed page can never be reused,
    so we make a new one whenever that happens."""
    context = await browser.new_context(
        viewport={"width": 1280, "height": 720},
        locale="en-IN",
        timezone_id="Asia/Kolkata",
    )
    await context.route("**/*", _route_filter)
    page = await context.new_page()
    page.set_default_timeout(NAV_TIMEOUT_MS)
    return context, page


# ---------------------------------------------------------------------------
# OLD extraction logic (2nd semester) — unchanged
# ---------------------------------------------------------------------------
async def data_extraction(page, roll):
    await page.goto(home, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)

    roll_input = page.locator("input[placeholder='ROLL NO']")
    await roll_input.wait_for(state="visible", timeout=15000)
    await roll_input.fill(str(roll))
    await roll_input.press("Enter")

    await page.wait_for_url(lambda url: url != home, timeout=20000)

    info = await page.evaluate("""() => {
        let a = {};
        for (let i = 0; i < 3; i++) {
            let parts = document
                .getElementsByClassName("table table-bordered")[1]
                .childNodes[1]
                .children[2]
                .querySelector("td")
                .childNodes[2]
                .getElementsByTagName("tr")[i]
                .innerText.split("\\t");

            let key = parts[0].trim().toLowerCase().replace(/ /g, "_").replace(/\\./g, "").replace(/'s/g, "");
            let val = parts[1]?.trim();

            a[key] = val;
        }
        return a;
    }""")

    marks = await page.evaluate("""() => {
        let x = [];
        let rows = document
            .getElementsByClassName("table table-bordered")[1]
            .childNodes[1]
            .children[2]
            .querySelector("td")
            .childNodes[4]
            .getElementsByTagName("tbody")[0]
            .children;

        for (let i = 1; i < rows.length - 1; i++) {
            let data = rows[i].innerText.split("\\t");
            x.push({
                subject: data[0]?.trim(),
                subject_code: data[1]?.trim(),
                credit: data[2]?.trim(),
                grade: data[3]?.trim()
            });
        }
        return x;
    }""")

    result = await page.evaluate("""() => {
        let arr = [];
        for (let i = 0; i < 3; i++) {
            let row = document
                .getElementsByClassName("table table-bordered")[1]
                .childNodes[1]
                .children[2]
                .querySelector("td")
                .childNodes[5]
                .getElementsByTagName("tbody")[0]
                .children[i];

            let parts = row.innerText.split("\\t");
            arr.push({ [parts[0].trim().toLowerCase().replace(/ /g, "_").replace(/\\./g, "")]: parts[1]?.trim() });
        }
        return arr;
    }""")

    return {"roll": roll, "personal_info": info, "marks": marks, "result": result}


# ---------------------------------------------------------------------------
# NEW extraction logic (4th semester)
# ---------------------------------------------------------------------------
async def data_extraction_4th_sem(page, roll):
    # domcontentloaded: don't wait for every ad/tracker/image to finish (that is what
    # was blowing up memory on Railway while "load" waited on them)
    await page.goto(sem_4_home, wait_until="domcontentloaded", timeout=NAV_TIMEOUT_MS)

    roll_input = page.locator("#RollNo")
    await roll_input.wait_for(state="visible", timeout=15000)
    await roll_input.fill(str(roll))
    await roll_input.press("Enter")

    # wait for the result table itself instead of a URL change (works for postbacks too)
    await page.locator("#midd_part_UN td.personal").first.wait_for(state="visible", timeout=20000)

    info = await page.evaluate("""() => {
        var child_count = document.getElementById('midd_part_UN').children[0].children[0].children.length;
        var main_content = document.getElementById('midd_part_UN').children[0].children[0].children[child_count-1];
        var info_table = main_content.children[0].children[1];
        var roll_no = info_table.getElementsByTagName('tr')[0].children[1].innerText.trim();
        var student_name = info_table.getElementsByTagName('tr')[1].children[1].innerText.trim();
        var father_name = info_table.getElementsByTagName('tr')[2].children[1].innerText.trim();
        var a = {};
        a['roll_no'] = roll_no;
        a['student_name'] = student_name;
        a['father_name'] = father_name;
        return a;
    }""")

    marks = await page.evaluate("""() => {
        var x = [];
        var child_count = document.getElementById('midd_part_UN').children[0].children[0].children.length;
        var main_content = document.getElementById('midd_part_UN').children[0].children[0].children[child_count-1];
        var marks_table = main_content.children[0].children[2].children[0].children;

        for (let i = 1; i < marks_table.length - 1; i++) {
            var data = String(marks_table[i].innerText).split("\\t").map(x => x.trim());
            x.push({
                subject: data[0]?.trim(),
                subject_code: data[1]?.trim(),
                credit: data[2]?.trim(),
                grade: data[3]?.trim()
            });
        }
        return x;
    }""")

    result = await page.evaluate("""() => {
        var child_count = document.getElementById('midd_part_UN').children[0].children[0].children.length;
        var main_content = document.getElementById('midd_part_UN').children[0].children[0].children[child_count-1];
        var result_table = main_content.children[0].children[3];

        var arr = [];
        for (var i = 0; i < 3; i++) {
            var data = String(result_table.children[0].children[i].innerText).split("\\t").map(function(x) { return x.trim(); });
            arr.push({ [data[0].toLowerCase()]: data[1] });
        }
        return arr;
    }""")

    return {"roll": roll, "personal_info": info, "marks": marks, "result": result}


# ---------------------------------------------------------------------------
# Shared streaming logic — with crash recovery
# ---------------------------------------------------------------------------
def _is_crash(err: Exception) -> bool:
    m = str(err).lower()
    return "crashed" in m or "target closed" in m or "has been closed" in m or "browser has disconnected" in m


async def stream_results(rolls, extractor):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=CHROMIUM_ARGS)
        context, page = await new_page(browser)

        try:
            for roll in rolls:
                data = None
                last_err = None

                # up to 2 tries per roll: if the page crashed, throw it away and retry on a fresh one
                for attempt in (1, 2):
                    try:
                        data = await extractor(page, roll)
                        break
                    except Exception as e:
                        last_err = e
                        if _is_crash(e):
                            print(f"[HPTU] page crashed on roll {roll} (attempt {attempt}) — new page")
                            try:
                                await context.close()
                            except Exception:
                                pass
                            try:
                                context, page = await new_page(browser)
                            except Exception:
                                # whole browser died — relaunch it
                                try:
                                    await browser.close()
                                except Exception:
                                    pass
                                browser = await p.chromium.launch(headless=True, args=CHROMIUM_ARGS)
                                context, page = await new_page(browser)
                            continue
                        break  # normal error (roll not found etc.) — no point retrying

                if data is not None:
                    yield f"data: {json.dumps(data)}\n\n"
                else:
                    yield f"data: {json.dumps({'roll': roll, 'error': str(last_err)})}\n\n"

                await asyncio.sleep(0)
        finally:
            try:
                await browser.close()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.get("/results/stream")
async def stream_api(rolls: str):
    """Old semester results."""
    rolls = json.loads(rolls)
    return StreamingResponse(stream_results(rolls, data_extraction), media_type="text/event-stream")


@app.get("/results/4th-sem/stream")
async def stream_api_4th_sem(rolls: str):
    """4th semester results."""
    rolls = json.loads(rolls)
    return StreamingResponse(stream_results(rolls, data_extraction_4th_sem), media_type="text/event-stream")


@app.get("/results/{sem}/stream")
async def stream_api_by_sem(sem: int, rolls: str):
    """Unified endpoint: /results/4/stream?rolls=[...] picks the right extractor by semester number."""
    rolls = json.loads(rolls)
    extractor = data_extraction_4th_sem if sem == 4 else data_extraction
    return StreamingResponse(stream_results(rolls, extractor), media_type="text/event-stream")


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/")
@app.get("/info")
def info():
    return {
        "old_sem": "http://localhost:8000/results/stream?rolls=[240603010065,240603010066]",
        "4th_sem": "http://localhost:8000/results/4th-sem/stream?rolls=[240603010065,240603010066]",
        "unified_example": "http://localhost:8000/results/4/stream?rolls=[240603010065,240603010066]",
    }


# uvicorn hptu_results_merged:app
