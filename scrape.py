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


def pick(page, label, option):
    """라벨 글자 뒤에 나오는 첫 select에서 option 선택"""
    page.locator(f"xpath=//*[contains(normalize-space(text()),'{label}')]/following::select[1]") \
        .first.select_option(label=option)


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


def search(page, sido, sigungu):
    """★ 사이트 구조에 맞춰 고쳐야 하는 부분. debug/ 스크린샷·HTML을 보고 수정하세요."""
    page.goto(URL, wait_until="networkidle")
    page.wait_for_timeout(1500)
    close_popups(page)
    page.get_by_text("물건상세검색").first.click()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    close_popups(page)
    pick(page, "소재지", sido)
    if sigungu:
        pick(page, "시군구", sigungu)
    pick(page, "용도", "아파트")
    page.get_by_role("button", name="검색").first.click()
    page.wait_for_load_state("networkidle")


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
        for i, (sido, sg) in enumerate(TARGETS):
            try:
                search(page, sido, sg)
                for n in range(MAX_PAGES):
                    for it in parse(page):
                        found[it["no"]] = it
                    nxt = page.get_by_role("link", name="다음").first
                    if not nxt.count() or not nxt.is_enabled():
                        break
                    nxt.click()
                    page.wait_for_load_state("networkidle")
                dump(page, f"ok_{i}")
            except Exception as e:
                print("실패", sido, sg, e)
                dump(page, f"err_{i}")
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
