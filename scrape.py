import json, os, re
from datetime import datetime, timedelta, timezone
from playwright.sync_api import sync_playwright

KST = timezone(timedelta(hours=9))
TODAY = datetime.now(KST).strftime("%Y-%m-%d")
URL = "https://www.courtauction.go.kr"
TARGETS = [("서울특별시", None)] + [("경기도", g) for g in
          ["성남시", "하남시", "광주시", "용인시", "이천시", "여주시", "양평군"]]
MAX_PAGES = 10
os.makedirs("debug", exist_ok=True)


def dump(page, name):
    try:
        page.screenshot(path=f"debug/{name}.png", full_page=True)
        open(f"debug/{name}.html", "w", encoding="utf-8").write(page.content())
    except Exception as e:
        print("dump fail", e)


def close_popups(page):
    """공지 팝업(w2popup_window)이 메뉴를 가리므로 닫거나 제거"""
    for _ in range(6):
        pops = page.locator(".w2popup_window:visible")
        if pops.count() == 0:
            break
        pop = pops.first
        btn = pop.get_by_text(re.compile("닫기|오늘.*열지")).or_(
            pop.locator("[class*='close' i], [id*='close' i]")).first
        try:
            btn.click(timeout=2000)
        except Exception:
            page.evaluate("document.querySelectorAll("
                          "'.w2popup_window, [class*=w2window_modal], .w2modal_popup')"
                          ".forEach(e => e.remove())")
        page.wait_for_timeout(300)


def sel_opts(el):
    return el.evaluate("e => [...e.options].map(o => o.text.trim())")


def find_sel(page, match):
    """옵션 내용으로 select를 찾는다 → (select, 일치 옵션 목록)"""
    sels = page.locator("select")
    for i in range(sels.count()):
        el = sels.nth(i)
        try:
            if not el.is_visible():
                continue
            hits = [t for t in sel_opts(el) if t and match(t)]
        except Exception:
            continue
        if hits:
            return el, hits
    return None, []


def pick(page, match, label=None):
    el, hits = find_sel(page, match)
    if el is None:
        raise Exception("select를 찾지 못함")
    el.select_option(label=label or hits[0])
    page.wait_for_timeout(900)
    return hits


def dump_selects(page, name):
    lines = []
    sels = page.locator("select")
    for i in range(sels.count()):
        el = sels.nth(i)
        try:
            lines.append(f"{el.get_attribute('id')} | {el.get_attribute('title')} | "
                         f"visible={el.is_visible()} | {sel_opts(el)[:15]}")
        except Exception as e:
            lines.append(f"{i} err {e}")
    open(f"debug/{name}.txt", "w", encoding="utf-8").write("\n".join(lines))


def open_search(page):
    page.goto(URL, wait_until="networkidle")
    page.wait_for_timeout(1500)
    close_popups(page)
    page.get_by_text("물건상세검색").first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    close_popups(page)


def set_usage(page):
    """용도: 건물 > 주거용건물 > 아파트 (있는 단계만 시도)"""
    for want in ("건물", "주거용건물", "아파트"):
        try:
            pick(page, lambda t, w=want: t == w)
        except Exception as e:
            print("용도 단계 건너뜀:", want, e)


def run_search(page):
    page.get_by_role("button", name=re.compile(r"^\s*검색\s*$")).first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)


def parse(page):
    out = []
    for tr in page.locator("tr").all():
        t = " ".join(tr.inner_text().split())
        m = re.search(r"\d{4}\s*타경\s*\d+", t)
        if not m or "아파트" not in t:
            continue
        nums = [int(x.replace(",", "")) for x in re.findall(r"\d{1,3}(?:,\d{3}){2,}", t)]
        ad = re.search(r"(서울특별시|경기도)\s\S+\s\S+(?:\s\S+){0,4}", t)
        dt = re.search(r"\d{4}[.\-]\d{2}[.\-]\d{2}", t)
        fl = re.search(r"유찰\s*(\d+)", t)
        ar = re.search(r"([\d.]+)\s*(?:㎡|m²)", t)
        out.append({
            "src": "법원경매", "no": re.sub(r"\s", "", m.group()),
            "addr": ad.group() if ad else t[:60],
            "area": ar.group(1) if ar else "",
            "appr": nums[0] if len(nums) > 0 else 0,
            "low": nums[1] if len(nums) > 1 else (nums[0] if nums else 0),
            "fail": int(fl.group(1)) if fl else 0,
            "date": dt.group().replace(".", "-") if dt else "",
            "url": URL,
        })
    return out


def main():
    found = {}
    with sync_playwright() as p:
        b = p.chromium.launch()
        page = b.new_context(locale="ko-KR", viewport={"width": 1400, "height": 1000}).new_page()
        n_run = 0
        for sido, key in TARGETS:
            try:
                open_search(page)
                dump_selects(page, f"selects_{n_run}_open")
                skey = "서울" if sido.startswith("서울") else "경기"
                pick(page, lambda t, k=skey: t in (k, k + "도", k + "특별시"))
                names = [None]
                if key:
                    _, names = find_sel(page, lambda t, k=key: k in t)
                    names = names or []
                    print(sido, key, "시군구 옵션:", names)
                for nm in names:
                    n_run += 1
                    try:
                        if nm:
                            pick(page, lambda t, x=nm: t == x)
                        set_usage(page)
                        dump_selects(page, f"selects_{n_run}")
                        run_search(page)
                        for _ in range(MAX_PAGES):
                            for it in parse(page):
                                found[it["no"]] = it
                            nxt = page.get_by_role("link", name="다음").first
                            if not nxt.count() or not nxt.is_enabled():
                                break
                            nxt.click()
                            page.wait_for_load_state("networkidle")
                        dump(page, f"ok_{n_run}")
                    except Exception as e:
                        print("실패", sido, nm, e)
                        dump(page, f"err_{n_run}")
            except Exception as e:
                print("실패", sido, key, e)
                dump(page, f"err_open_{n_run}")
        b.close()

    if not found:
        print("수집 0건 - data.json 유지")
        raise SystemExit(1)

    old = {}
    if os.path.exists("data.json"):
        for x in json.load(open("data.json", encoding="utf-8")).get("items", []):
            old[x["no"]] = x.get("reg")
    for k, it in found.items():
        it["reg"] = old.get(k) or TODAY
    json.dump({"updated": datetime.now(KST).strftime("%Y-%m-%d %H:%M"),
               "items": list(found.values())},
              open("data.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("저장", len(found))


main()
