import json
import asyncio
import sys
import os
import time
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from playwright.async_api import async_playwright

if sys.platform=="win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())


home="https://results.indiaresults.com/hp/himtu/hp-himtu/mquery.aspx?id=1800266513"
sem_4_home= "https://himturesult.indiaresults.com/hp/himtu/hp-himtu/query.aspx?chk=Y&id=1800267004"

CHROMIUM_ARGS=["--disable-dev-shm-usage","--no-sandbox","--disable-setuid-sandbox","--disable-gpu","--disable-extensions","--disable-background-networking", "--disable-default-apps","--mute-audio","--no-first-run",]
NAV_TIMEOUT_MS= 45000
BLOCK_HEAVY=os.getenv("BLOCK_HEAVY","1")=="1"
BLOCKED_TYPES={"image" , "media","font"}
BLOCKED_HOSTS=("google-analytics","googletagmanager","doubleclick" ,"googlesyndication","facebook","adservice","hotjar","clarity.ms")

app=FastAPI()


HPTU_DEBUG =os.getenv("HPTU_DEBUG","1")=="1"


def dbg(roll,msg):
    if HPTU_DEBUG:
        print(f"[HPTU4][{roll}] {time.strftime('%H:%M:%S')} {msg}",flush=True)


def mem_info():
    out=[]
    for used_p,max_p in (("/sys/fs/cgroup/memory.current","/sys/fs/cgroup/memory.max"),("/sys/fs/cgroup/memory/memory.usage_in_bytes" ,"/sys/fs/cgroup/memory/memory.limit_in_bytes")):
        try:
            used=int(open(used_p).read().strip()) / 1048576
            mx=open(max_p).read().strip()
            mx="unlimited" if mx=="max" else f"{int(mx)/1048576:.0f}MB"
            out.append(f"container={used:.0f}MB/{mx}")
            break
        except Exception:
            continue
    try:
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable"):
                out.append(f"host_avail={int(line.split()[1])/1024:.0f}MB")
                break
    except Exception:
        pass
    try:
        shm=os.statvfs("/dev/shm")
        out.append(f"/dev/shm_free={shm.f_bavail*shm.f_frsize/1048576:.0f}MB")
    except Exception:
        pass
    return " ".join(out) or "n/a"


def attach_debug_listeners(page,roll_ref):
    if getattr(page,"_hptu_dbg",False):
        return
    page._hptu_dbg = True

    page.on("crash",lambda:dbg(roll_ref[0],f"!!! PAGE CRASH EVENT | {mem_info()}"))
    page.on("pageerror",lambda e:dbg(roll_ref[0],f"pageerror: {str(e)[:200]}"))
    page.on("console",lambda m:dbg(roll_ref[0],f"console.{m.type}: {m.text[:200]}")if m.type=="error" else None)
    page.on("requestfailed" ,lambda r:dbg(roll_ref[0],f"requestfailed: {r.resource_type} {r.url[:110]} -> {r.failure}")if "abort" not in str(r.failure).lower()else None)
    page.on("response",lambda r:dbg(roll_ref[0],f"doc response {r.status} {r.url[:110]}")if r.request.resource_type=="document" else None)
    page.on("close",lambda:dbg(roll_ref[0],"page closed"))



async def _route_filter(route):
    req=route.request
    url=req.url.lower()
    if req.resource_type in BLOCKED_TYPES or any(h in url for h in BLOCKED_HOSTS):
        await route.abort()
    else:
        await route.continue_()


async def new_page(browser):
    context=await browser.new_context(viewport={"width":1280,"height":720},locale="en-IN",timezone_id="Asia/Kolkata",)
    if BLOCK_HEAVY:
        await context.route("**/*",_route_filter)
    page = await context.new_page()
    page.set_default_timeout(NAV_TIMEOUT_MS)
    return context ,page



async def data_extraction(page,roll):
    await page.goto(home,wait_until="domcontentloaded" ,timeout=NAV_TIMEOUT_MS)

    roll_input=page.locator("input[placeholder='ROLL NO']")
    await roll_input.wait_for(state="visible",timeout=15000)
    await roll_input.fill(str(roll))
    await roll_input.press("Enter")

    await page.wait_for_url(lambda url:url!=home,timeout=20000)

    info=await page.evaluate("""() => { let a = {};for (let i = 0;i < 3;i++) { let parts = document .getElementsByClassName("table table-bordered")[1] .childNodes[1] .children[2] .querySelector("td") .childNodes[2] .getElementsByTagName("tr")[i] .innerText.split("\\t");let key = parts[0].trim().toLowerCase().replace(/ /g, "_").replace(/\\./g, "").replace(/'s/g, ""); let val = parts[1]?.trim(); a[key] = val; } return a; }""")

    marks=await page.evaluate("""() => { let x = [];let rows = document .getElementsByClassName("table table-bordered")[1] .childNodes[1] .children[2] .querySelector("td") .childNodes[4] .getElementsByTagName("tbody")[0] .children;for (let i = 1;i < rows.length - 1;i++) { let data = rows[i].innerText.split("\\t");x.push({ subject:data[0]?.trim(), subject_code:data[1]?.trim(), credit:data[2]?.trim(), grade:data[3]?.trim() });} return x ;}""")

    result= await page.evaluate("""() => { let arr = [];for (let i = 0;i < 3;i++) { let row = document .getElementsByClassName("table table-bordered")[1] .childNodes[1] .children[2] .querySelector("td") .childNodes[5] .getElementsByTagName("tbody")[0] .children[i];let parts = row.innerText.split("\\t");arr.push({ [parts[0].trim().toLowerCase().replace(/ /g, "_").replace(/\\./g, "")]:parts[1]?.trim() });} return arr;}""")

    return {"roll":roll,"personal_info":info,"marks":marks,"result":result}


_dbg_roll=[""]


async def _data_extraction_4th_sem(page,roll):
    t0=time.perf_counter()
    _dbg_roll[0]=roll
    attach_debug_listeners(page,_dbg_roll)
    dbg(roll,f"START | {mem_info()}")

    dbg(roll,f"goto -> {sem_4_home[:70]}")
    resp=await page.goto(sem_4_home,wait_until="domcontentloaded",timeout=NAV_TIMEOUT_MS)
    dbg(roll,f"goto done status={resp.status if resp else None} url={page.url[:90]} "f"({time.perf_counter()-t0:.1f}s) | {mem_info()}")

    roll_input=page.locator("#RollNo")
    dbg(roll,"waiting for #RollNo")
    await roll_input.wait_for(state="visible",timeout=15000)
    dbg(roll,f"#RollNo visible ({time.perf_counter()-t0:.1f}s), filling + Enter")
    await roll_input.fill(str(roll))
    await roll_input.press("Enter")
    dbg(roll,"Enter pressed, waiting for result table")


    await page.locator("#midd_part_UN td.personal").first.wait_for(state="visible",timeout=20000)
    dbg(roll,f"result table visible ({time.perf_counter()-t0:.1f}s) url={page.url[:90]} | {mem_info()}")

    info= await page.evaluate("""() => { var child_count = document.getElementById('midd_part_UN').children[0].children[0].children.length;var main_content = document.getElementById('midd_part_UN').children[0].children[0].children[child_count-1];var info_table = main_content.children[0].children[1];var roll_no = info_table.getElementsByTagName('tr')[0].children[1].innerText.trim();var student_name = info_table.getElementsByTagName('tr')[1].children[1].innerText.trim();var father_name = info_table.getElementsByTagName('tr')[2].children[1].innerText.trim();var a = {};a['roll_no'] = roll_no ;a['student_name'] = student_name;a['father_name'] = father_name;return a;}""")

    dbg(roll,f"info extracted: {info}")

    marks=await page.evaluate("""() => { var x = [];var child_count = document.getElementById('midd_part_UN').children[0].children[0].children.length;var main_content = document.getElementById('midd_part_UN').children[0].children[0].children[child_count-1];var marks_table = main_content.children[0].children[2].children[0].children;for (let i = 1;i < marks_table.length - 1;i++) { var data = String(marks_table[i].innerText).split("\\t").map(x => x.trim());x.push({ subject:data[0]?.trim(), subject_code:data[1]?.trim(), credit:data[2]?.trim(), grade:data[3]?.trim() });} return x;}""")

    dbg(roll,f"marks extracted: {len(marks)} subjects")

    result=await page.evaluate("""() => { var child_count = document.getElementById('midd_part_UN').children[0].children[0].children.length;var main_content = document.getElementById('midd_part_UN').children[0].children[0].children[child_count-1];var result_table = main_content.children[0].children[3];var arr = [];for (var i = 0;i < 3;i++) { var data = String(result_table.children[0].children[i].innerText).split("\\t").map(function(x) { return x.trim();});arr.push({ [data[0].toLowerCase()]:data[1] });} return arr;}""")

    dbg(roll ,f"result extracted: {result} | DONE in {time.perf_counter()-t0:.1f}s | {mem_info()}")
    return {"roll":roll,"personal_info":info,"marks":marks,"result":result}


async def data_extraction_4th_sem(page,roll):
    try:
        return await _data_extraction_4th_sem(page,roll)
    except Exception as e:
        dbg(roll,f"FAILED: {type(e).__name__}: {str(e).splitlines()[0][:200]} | {mem_info()}")
        if _is_crash(e):
            raise
        try:
            title=await page.title()
            body=await page.evaluate("document.body ? document.body.innerText.slice(0, 250).replace(/\\s+/g, ' ') : ''")
            extra=f" | url={page.url!r} | title={title!r} | body={body!r}"
            dbg(roll,f"page state at failure:{extra}")
        except Exception:
            extra=""
        raise RuntimeError(f"{type(e).__name__}: {str(e).splitlines()[0]}{extra}")



def _is_crash(err:Exception) -> bool:
    m=str(err).lower()
    return "crashed" in m or "target closed" in m or "has been closed" in m or "browser has disconnected" in m


async def stream_results(rolls,extractor):
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True ,args=CHROMIUM_ARGS)
        dbg("-",f"browser launched v{browser.version} BLOCK_HEAVY={BLOCK_HEAVY} rolls={len(rolls)} | {mem_info()}")
        context,page=await new_page(browser)

        try:
            for roll in rolls:
                data=None
                last_err=None


                for attempt in (1,2):
                    try:
                        data=await extractor(page,roll)
                        break
                    except Exception as e:
                        last_err=e
                        if _is_crash(e):
                            print(f"[HPTU] page crashed on roll {roll} (attempt {attempt}) — new page")
                            try:
                                await context.close()
                            except Exception:
                                pass
                            try:
                                context,page= await new_page(browser)
                            except Exception:
                                try:
                                    await browser.close()
                                except Exception:
                                    pass
                                browser=await p.chromium.launch(headless=True,args=CHROMIUM_ARGS)
                                context,page=await new_page(browser)
                            continue
                        break

                if data is not None:
                    yield f"data: {json.dumps(data)}\n\n"
                else:
                    yield f"data: {json.dumps({'roll':roll,'error':str(last_err)})}\n\n"

                await asyncio.sleep(0)

        finally:
            try:
                await browser.close()
            except Exception:
                pass



@app.get("/results/stream")
async def stream_api(rolls:str):
    rolls=json.loads(rolls)
    return StreamingResponse(stream_results(rolls , data_extraction),media_type="text/event-stream")


@app.get("/results/4th-sem/stream")
async def stream_api_4th_sem(rolls:str):
    rolls=json.loads(rolls)
    return StreamingResponse(stream_results(rolls,data_extraction_4th_sem),media_type="text/event-stream")


@app.get("/results/{sem}/stream")
async def stream_api_by_sem(sem:int,rolls:str):
    rolls=json.loads(rolls)
    extractor=data_extraction_4th_sem if sem==4 else data_extraction
    return StreamingResponse(stream_results(rolls,extractor), media_type="text/event-stream")


@app.get("/health")
def health():
    return {"status":"healthy"}


@app.get("/")
@app.get("/info")
def info():
    return {"old_sem":"https://railwayhptu-production.up.railway.app/results/stream?rolls=[240603010065,240603010066]","4th_sem":"https://railwayhptu-production.up.railway.app/results/4th-sem/stream?rolls=[240603010065,240603010066]","unified_example":"https://railwayhptu-production.up.railway.app/results/4/stream?rolls=[240603010065,240603010066]" ,}



