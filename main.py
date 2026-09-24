import json
import asyncio
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from playwright.async_api import async_playwright
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# ---- URLs ----
home = "https://results.indiaresults.com/hp/himtu/hp-himtu/mquery.aspx?id=1800266513"
sem_4_home = "https://himturesult.indiaresults.com/hp/himtu/hp-himtu/query.aspx?chk=Y&id=1800267004"

app = FastAPI()


# ---------------------------------------------------------------------------
# OLD extraction logic (original semester)
# ---------------------------------------------------------------------------
async def data_extraction(page, roll):
    await page.goto(home)

    roll_input = page.locator("input[placeholder='ROLL NO']")
    await roll_input.wait_for(state="visible", timeout=8000)
    await roll_input.fill(str(roll))
    await roll_input.press("Enter")

    await page.wait_for_url(lambda url: url != home, timeout=10000)

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

    print(46, info)

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

    print(71, marks)

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

    print(result)

    return {
        "roll": roll,
        "personal_info": info,
        "marks": marks,
        "result": result
    }


# ---------------------------------------------------------------------------
# NEW extraction logic (4th semester)
# ---------------------------------------------------------------------------
async def data_extraction_4th_sem(page, roll):
    await page.goto(sem_4_home)

    roll_input = page.locator("#RollNo")
    await roll_input.wait_for(state="visible", timeout=8000)
    await roll_input.fill(str(roll))
    await roll_input.press("Enter")

    await page.wait_for_url(lambda url: url != sem_4_home, timeout=10000)

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

    print(46, info)

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

    print(71, marks)

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

    print(result)

    return {
        "roll": roll,
        "personal_info": info,
        "marks": marks,
        "result": result
    }


# ---------------------------------------------------------------------------
# Shared streaming logic — picks the extraction fn to run per roll
# ---------------------------------------------------------------------------
async def stream_results(rolls, extractor):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()

        for roll in rolls:
            try:
                data = await extractor(page, roll)
                yield f"data: {json.dumps(data)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'roll': roll, 'error': str(e)})}\n\n"

            await asyncio.sleep(0)

        await browser.close()


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

@app.get("/")
@app.get("/info")
def info():
    return {
        "old_sem": "http://localhost:8000/results/stream?rolls=[240603010065,240603010066,240603010067,240603010068,240603010069,240603010070,240603010071,240603010072,240603010073,240603010074,240603010075]",
        "4th_sem": "http://localhost:8000/results/4th-sem/stream?rolls=[240603010065,240603010066,240603010067,240603010068,240603010069,240603010070,240603010071,240603010072,240603010073,240603010074,240603010075]",
        "unified_example": "http://localhost:8000/results/4/stream?rolls=[240603010065,240603010066,240603010067,240603010068,240603010069,240603010070,240603010071,240603010072,240603010073,240603010074,240603010075]"
    }


# uvicorn hptu_results_merged:app
